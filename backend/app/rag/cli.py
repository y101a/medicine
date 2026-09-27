import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import KnowledgeDocument, KnowledgeSource
from app.rag.evaluation import RetrievalEvaluationError, run_prototype_evaluation
from app.rag.markdown_importer import ControlledImportError, import_markdown_document
from app.rag.prototype_seed import PrototypeSeedError, seed_prototype_knowledge
from app.rag.retrieval import RETRIEVAL_MODES
from app.rag.source_sync import SourceRegistryError, sync_approved_sources
from app.rag.vectorizer import ControlledVectorizationError, vectorize_document


@dataclass(frozen=True, slots=True)
class PrototypeVectorizeResult:
    document_count: int
    generated_count: int
    duplicate_count: int
    document_ids: tuple[UUID, ...]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="受控医学知识库管理命令")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync-sources", help="同步注册表中已批准来源")
    sync_parser.add_argument("--registry", type=Path, default=None)

    import_parser = subparsers.add_parser(
        "import-markdown", help="导入一篇已完成审核的 Markdown"
    )
    import_parser.add_argument("--file", type=Path, required=True)
    import_parser.add_argument("--metadata", type=Path, required=True)

    vectorize_parser = subparsers.add_parser(
        "embed-document", help="为一篇已批准文档生成阿里云向量"
    )
    vectorize_parser.add_argument("--document-id", type=UUID, required=True)

    seed_parser = subparsers.add_parser(
        "seed-prototype", help="导入仅限开发环境的自编原型语料"
    )
    seed_parser.add_argument("--directory", type=Path, default=None)

    subparsers.add_parser(
        "embed-prototype", help="为当前原型语料生成阿里云向量"
    )
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
        "--mode",
        choices=RETRIEVAL_MODES,
        default="hybrid",
        help=(
            "检索模式：hybrid（默认，线上行为）；keyword 只走关键词且不调用向量服务"
            "（零成本，可用于对比漏召回）；vector 只走向量"
        ),
    )
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
            else:
                result = await run_prototype_evaluation(
                    db,
                    args.dataset,
                    top_k=args.top_k,
                    mode=args.mode,
                    split=args.split,
                )
            await db.commit()
        except (
            ControlledImportError,
            ControlledVectorizationError,
            PrototypeSeedError,
            RetrievalEvaluationError,
            SourceRegistryError,
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
