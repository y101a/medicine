import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import KnowledgeDocument, KnowledgeSource
from app.rag.evaluation import (
    RetrievalEvaluationError,
    build_report,
    load_results_report,
    regate_case,
    run_prototype_evaluation,
    split_report,
    sweep_report,
    threshold_grid,
)
from app.rag.markdown_importer import ControlledImportError, import_markdown_document
from app.rag.prototype_seed import PrototypeSeedError, seed_prototype_knowledge
from app.rag.relevance import (
    RELEVANCE_GATE_PROFILES,
    candidate_threshold_gate,
    gate_from_profile,
)
from app.rag.retrieval import RETRIEVAL_MODES
from app.rag.source_sync import SourceRegistryError, sync_approved_sources
from app.rag.vectorizer import ControlledVectorizationError, vectorize_document


@dataclass(frozen=True, slots=True)
class PrototypeVectorizeResult:
    document_count: int
    generated_count: int
    duplicate_count: int
    document_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class RelevanceGateSweepResult:
    """离线扫参结果：不重新检索，只换门槛重算（阶段 C 的选参入口）。"""

    mode: str
    evaluation_split: str
    gates_evaluated: int
    selected: dict[str, object] | None
    sweep: dict[str, object]


def parse_float_list(raw: str) -> list[float]:
    try:
        values = [float(part) for part in raw.split(",") if part.strip()]
    except ValueError as exc:
        raise ValueError(f"阈值列表无法解析：{raw}") from exc
    if not values:
        raise ValueError("阈值列表不能为空")
    return values


def run_relevance_gate_sweep(args: argparse.Namespace) -> RelevanceGateSweepResult:
    """在 result JSON 上离线扫参；holdout 只允许在门槛冻结后复算。

    纪律写进代码而不是写在文档里：`--split holdout` **必须**同时给出 `--frozen-*` 阈值，
    否则直接报错——这样就不会出现「看了 holdout 再回头调参」。
    """
    report = split_report(load_results_report(args.results), args.split)
    frozen_vector = args.frozen_vector_threshold
    frozen_keyword = args.frozen_keyword_threshold
    if frozen_vector is not None or frozen_keyword is not None:
        if frozen_vector is None or frozen_keyword is None:
            raise ValueError("冻结复算需要同时给出向量阈值与关键词阈值")
        gate = candidate_threshold_gate(
            vector_threshold=frozen_vector,
            keyword_threshold=frozen_keyword,
            keyword_only_threshold=(
                args.frozen_keyword_only_threshold
                if args.frozen_keyword_only_threshold is not None
                else frozen_keyword
            ),
        )
        gated = build_report(
            [regate_case(case, gate) for case in report.cases],
            mode=report.mode,
            split=args.split,
            top_k=report.top_k,
            retry_count=report.retry_count,
            gate=gate,
        )
        sweep = sweep_report(report, [gate])
        return RelevanceGateSweepResult(
            mode="frozen",
            evaluation_split=args.split,
            gates_evaluated=1,
            selected={
                "profile": gate.profile,
                "thresholds": gate.thresholds(),
                "recallAt3": gated.recall_at_3,
                "passRate": gated.pass_rate,
                "unsupportedFalsePositiveRate": gated.unsupported_false_positive_rate,
            },
            sweep=sweep,
        )
    if args.split == "holdout":
        raise ValueError("holdout 只能在门槛冻结后复算，请给出 --frozen-* 阈值")
    gates = threshold_grid(
        vector_thresholds=parse_float_list(args.vector_thresholds),
        keyword_thresholds=parse_float_list(args.keyword_thresholds),
        keyword_only_thresholds=parse_float_list(args.keyword_only_thresholds),
    )
    sweep = sweep_report(report, gates)
    return RelevanceGateSweepResult(
        mode="sweep",
        evaluation_split=args.split,
        gates_evaluated=len(gates),
        selected=sweep["selected"],  # type: ignore[arg-type]
        sweep=sweep,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="受控医学知识库管理命令")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync-sources", help="同步注册表中已批准来源")
    sync_parser.add_argument("--registry", type=Path, default=None)

    import_parser = subparsers.add_parser("import-markdown", help="导入一篇已完成审核的 Markdown")
    import_parser.add_argument("--file", type=Path, required=True)
    import_parser.add_argument("--metadata", type=Path, required=True)

    vectorize_parser = subparsers.add_parser(
        "embed-document", help="为一篇已批准文档生成阿里云向量"
    )
    vectorize_parser.add_argument("--document-id", type=UUID, required=True)

    seed_parser = subparsers.add_parser("seed-prototype", help="导入仅限开发环境的自编原型语料")
    seed_parser.add_argument("--directory", type=Path, default=None)

    subparsers.add_parser("embed-prototype", help="为当前原型语料生成阿里云向量")
    evaluation_parser = subparsers.add_parser(
        "evaluate-prototype", help="运行仅限开发用途的原型语料检索评测"
    )
    evaluation_parser.add_argument("--dataset", type=Path, default=None)
    evaluation_parser.add_argument("--top-k", type=int, default=3, choices=range(1, 11))
    evaluation_parser.add_argument(
        "--split",
        choices=("all", "tune", "holdout"),
        default="all",
        help="题集分组：日常调参用 tune；方案冻结后才运行 holdout；旧题集使用 all",
    )
    evaluation_parser.add_argument(
        "--max-retries",
        type=int,
        choices=range(0, 6),
        default=2,
        help="单道题遇到向量服务超时、暂时不可用或限流时的最大重试次数",
    )
    evaluation_parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="可选断点 JSON；每题成功后原子写入，再次运行时跳过已完成题",
    )
    evaluation_parser.add_argument(
        "--mode",
        choices=RETRIEVAL_MODES,
        default="hybrid",
        help=(
            "检索模式：hybrid（默认，线上行为）；keyword 只走关键词且不调用向量服务"
            "（零成本，可用于对比漏召回）；vector 只走向量"
        ),
    )
    evaluation_parser.add_argument(
        "--gate-profile",
        choices=RELEVANCE_GATE_PROFILES,
        default="none",
        help=(
            "相关度门槛：none（默认，与历史评测结果逐位对齐）；"
            "current-consultation（精确复刻咨询链路现有门槛）；"
            "candidate-threshold（待调门槛，必须同时给出 --gate-vector-threshold 与 "
            "--gate-keyword-threshold）"
        ),
    )
    evaluation_parser.add_argument(
        "--gate-vector-threshold",
        type=float,
        default=None,
        help="candidate-threshold 的向量门槛（0-1）；只允许在 tune 集上选择",
    )
    evaluation_parser.add_argument(
        "--gate-keyword-threshold",
        type=float,
        default=None,
        help="有向量但向量分不足时，关键词分需要达到的补充证据门槛（0-1）",
    )
    evaluation_parser.add_argument(
        "--gate-keyword-only-threshold",
        type=float,
        default=None,
        help="没有当前向量的候选（含无向量精确关键词命中）单独使用的门槛（0-1）",
    )

    sweep_parser = subparsers.add_parser(
        "sweep-relevance-gate",
        help="在已保存的真实召回结果上离线换门槛（不重新检索、不重复付费）",
    )
    sweep_parser.add_argument(
        "results",
        type=Path,
        help="evaluate-prototype 写出的结果 JSON（必须含逐候选分数）",
    )
    sweep_parser.add_argument(
        "--split",
        choices=("tune", "holdout", "all"),
        default="tune",
        help="选参数只看 tune；holdout 必须配合 --frozen-* 阈值才能复算",
    )
    sweep_parser.add_argument(
        "--vector-thresholds",
        default="0.45,0.5,0.55,0.6,0.65,0.7,0.75",
    )
    sweep_parser.add_argument(
        "--keyword-thresholds",
        default="0.2,0.3,0.4,0.5,0.6",
    )
    sweep_parser.add_argument(
        "--keyword-only-thresholds",
        default="0.2,0.35,0.5,0.8",
    )
    sweep_parser.add_argument("--frozen-vector-threshold", type=float, default=None)
    sweep_parser.add_argument("--frozen-keyword-threshold", type=float, default=None)
    sweep_parser.add_argument("--frozen-keyword-only-threshold", type=float, default=None)
    return parser


async def run_command(args: argparse.Namespace) -> int:
    async with SessionLocal() as db:
        try:
            if args.command == "sync-sources":
                result = await sync_approved_sources(db, args.registry)
            elif args.command == "import-markdown":
                result = await import_markdown_document(db, args.file, args.metadata)
            elif args.command == "embed-document":
                result = await vectorize_document(db, args.document_id)
            elif args.command == "seed-prototype":
                result = await seed_prototype_knowledge(db, args.directory)
            elif args.command == "embed-prototype":
                document_ids = tuple(
                    await db.scalars(
                        select(KnowledgeDocument.id)
                        .join(
                            KnowledgeSource,
                            KnowledgeSource.id == KnowledgeDocument.source_id,
                        )
                        .where(
                            KnowledgeSource.ingestion_status == "prototype",
                            KnowledgeDocument.review_status == "prototype",
                        )
                        .order_by(KnowledgeDocument.created_at)
                    )
                )
                generated = 0
                duplicates = 0
                for document_id in document_ids:
                    vectorized = await vectorize_document(db, document_id)
                    generated += int(not vectorized.duplicate)
                    duplicates += int(vectorized.duplicate)
                result = PrototypeVectorizeResult(
                    document_count=len(document_ids),
                    generated_count=generated,
                    duplicate_count=duplicates,
                    document_ids=document_ids,
                )
            elif args.command == "sweep-relevance-gate":
                result = run_relevance_gate_sweep(args)
            else:
                result = await run_prototype_evaluation(
                    db,
                    args.dataset,
                    top_k=args.top_k,
                    mode=args.mode,
                    split=args.split,
                    max_retries=args.max_retries,
                    checkpoint_path=args.checkpoint,
                    gate=gate_from_profile(
                        args.gate_profile,
                        vector_threshold=args.gate_vector_threshold,
                        keyword_threshold=args.gate_keyword_threshold,
                        keyword_only_threshold=args.gate_keyword_only_threshold,
                    ),
                )
            await db.commit()
        except (
            ControlledImportError,
            ControlledVectorizationError,
            PrototypeSeedError,
            RetrievalEvaluationError,
            SourceRegistryError,
            # 门槛参数不合法（例如 candidate-threshold 没给阈值）时给一行可读错误，不抛堆栈。
            ValueError,
        ) as exc:
            await db.commit()
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 1
    print(json.dumps({"ok": True, **asdict(result)}, ensure_ascii=False, default=str))
    return 0


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(run_command(args)))


if __name__ == "__main__":
    main()
