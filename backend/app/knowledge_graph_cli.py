"""受控知识图谱治理命令（G1）。

与 `app/rag/cli.py` 同一套约定：argparse 子命令 + 一行 JSON 结果 + 退出码 0/1，便于脚本与
人工核对。**不提供任何公网写接口**——没有管理员端之前，写操作只走这个前台命令。

用法示例：
    python -m app.knowledge_graph_cli seed-concepts --file concepts.json
    python -m app.knowledge_graph_cli extract-candidates --all-approved --dry-run
    python -m app.knowledge_graph_cli review-queue --limit 10
    python -m app.knowledge_graph_cli approve-claim --claim <uuid> --actor 李医生
    python -m app.knowledge_graph_cli publish --actor 李医生
    python -m app.knowledge_graph_cli verify
"""

import argparse
import asyncio
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from app.db.session import SessionLocal
from app.schemas.knowledge_graph import GraphConceptSeedFile
from app.services import knowledge_graph_candidates as candidates
from app.services import knowledge_graph_publication as publication
from app.services import knowledge_graph_registry as registry
from app.services import knowledge_graph_review as review

_DOMAIN_ERRORS = (
    candidates.KnowledgeGraphExtractionError,
    publication.KnowledgeGraphPublicationError,
    registry.KnowledgeGraphRegistryError,
    review.KnowledgeGraphReviewError,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="受控公共医学知识图谱治理命令（G1）")
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed_parser = subparsers.add_parser("seed-concepts", help="按登记文件登记概念与别名")
    seed_parser.add_argument("--file", type=Path, required=True, help="概念登记 JSON")

    register_parser = subparsers.add_parser("register-concept", help="登记单个概念")
    register_parser.add_argument(
        "--type",
        dest="concept_type",
        required=True,
        help="topic|symptom|department|red_flag|self_care",
    )
    register_parser.add_argument("--name", required=True, help="规范名")
    register_parser.add_argument("--alias", action="append", default=[], help="别名，可重复")

    rename_parser = subparsers.add_parser(
        "rename-concept", help="改规范名（ID 不变，旧名自动留成别名）"
    )
    rename_parser.add_argument("--concept", type=UUID, required=True)
    rename_parser.add_argument("--name", required=True, help="新的规范名")

    extract_parser = subparsers.add_parser("extract-candidates", help="为已审核文档抽取候选关系")
    extract_target = extract_parser.add_mutually_exclusive_group(required=True)
    extract_target.add_argument("--document", type=UUID, help="单篇文档 ID")
    extract_target.add_argument("--all-approved", action="store_true", help="批量处理已审核文档")
    extract_parser.add_argument("--limit", type=int, default=20, help="批量模式最多处理几篇")
    extract_parser.add_argument("--dry-run", action="store_true", help="只报数量，不写库")

    queue_parser = subparsers.add_parser("review-queue", help="待审核队列（含证据原文）")
    queue_parser.add_argument("--limit", type=int, default=20)
    queue_parser.add_argument(
        "--decision",
        default="pending",
        choices=["pending", "approved", "rejected", "returned"],
    )

    approve_parser = subparsers.add_parser("approve-claim", help="医学审核通过")
    approve_parser.add_argument("--claim", type=UUID, required=True)
    approve_parser.add_argument("--actor", required=True, help="审核人")
    approve_parser.add_argument("--note", default=None)

    reject_parser = subparsers.add_parser("reject-claim", help="拒绝候选（必须写原因）")
    reject_parser.add_argument("--claim", type=UUID, required=True)
    reject_parser.add_argument("--actor", required=True)
    reject_parser.add_argument("--note", required=True)

    return_parser = subparsers.add_parser("return-claim", help="退回修改（必须写原因）")
    return_parser.add_argument("--claim", type=UUID, required=True)
    return_parser.add_argument("--actor", required=True)
    return_parser.add_argument("--note", required=True)

    retire_parser = subparsers.add_parser("retire-claim", help="撤回已审核/已发布关系")
    retire_parser.add_argument("--claim", type=UUID, required=True)
    retire_parser.add_argument("--actor", required=True)
    retire_parser.add_argument("--reason", required=True)

    stale_parser = subparsers.add_parser("retire-stale", help="批量撤回来源已失效的关系")
    stale_parser.add_argument("--actor", required=True)
    stale_parser.add_argument("--reason", default="来源文档已失效或正文已变更")

    bind_parser = subparsers.add_parser("bind-evidence", help="人工补一条证据")
    bind_parser.add_argument("--claim", type=UUID, required=True)
    bind_parser.add_argument("--chunk", type=UUID, required=True)
    bind_parser.add_argument("--span-start", type=int, default=None)
    bind_parser.add_argument("--span-end", type=int, default=None)

    publish_parser = subparsers.add_parser("publish", help="把已审核关系登记为新 revision")
    publish_parser.add_argument("--actor", required=True)

    rebuild_parser = subparsers.add_parser("rebuild-snapshot", help="强制排队全量快照重建")
    rebuild_parser.add_argument("--actor", required=True)

    subparsers.add_parser("status", help="图谱治理状态")
    subparsers.add_parser("verify", help="硬门槛校验（有违规时退出码 1）")
    subparsers.add_parser("publication-status", help="发布 outbox 状态")

    claim_job = subparsers.add_parser("claim-job", help="取一个发布任务（G2 worker 用）")
    claim_job.add_argument("--owner", required=True)
    claim_job.add_argument("--lease-seconds", type=int, default=300)

    complete_job = subparsers.add_parser("complete-job", help="回写发布成功（G2 worker 用）")
    complete_job.add_argument("--job", type=UUID, required=True)
    complete_job.add_argument("--owner", required=True)

    fail_job = subparsers.add_parser("fail-job", help="回写发布失败（G2 worker 用）")
    fail_job.add_argument("--job", type=UUID, required=True)
    fail_job.add_argument("--owner", required=True)
    fail_job.add_argument("--code", required=True)
    fail_job.add_argument("--message", required=True)
    return parser


async def run_command(args: argparse.Namespace) -> int:
    exit_code = 0
    async with SessionLocal() as db:
        try:
            if args.command == "seed-concepts":
                seed = GraphConceptSeedFile.model_validate_json(
                    args.file.read_text(encoding="utf-8")
                )
                result: object = await registry.seed_concepts(db, seed)
            elif args.command == "register-concept":
                result = await registry.register_concept(
                    db,
                    concept_type=args.concept_type,
                    canonical_name=args.name,
                    aliases=args.alias,
                )
            elif args.command == "rename-concept":
                result = await registry.rename_concept(db, args.concept, canonical_name=args.name)
            elif args.command == "extract-candidates":
                if args.document is not None:
                    result = await candidates.extract_document_candidates(
                        db, args.document, dry_run=args.dry_run
                    )
                else:
                    result = await candidates.extract_approved_candidates(
                        db, limit=args.limit, dry_run=args.dry_run
                    )
            elif args.command == "review-queue":
                result = await review.list_review_queue(
                    db, limit=args.limit, decision=args.decision
                )
            elif args.command == "approve-claim":
                result = await review.approve_claim(
                    db, args.claim, reviewer=args.actor, note=args.note
                )
            elif args.command == "reject-claim":
                result = await review.reject_claim(
                    db, args.claim, reviewer=args.actor, note=args.note
                )
            elif args.command == "return-claim":
                result = await review.return_claim(
                    db, args.claim, reviewer=args.actor, note=args.note
                )
            elif args.command == "retire-claim":
                result = await review.retire_claim(
                    db, args.claim, reviewer=args.actor, reason=args.reason
                )
            elif args.command == "retire-stale":
                retired = await review.retire_stale_claims(
                    db, reviewer=args.actor, reason=args.reason
                )
                result = {"retired_claim_ids": retired, "retired_count": len(retired)}
            elif args.command == "bind-evidence":
                evidence_id = await review.bind_evidence(
                    db,
                    args.claim,
                    args.chunk,
                    span_start=args.span_start,
                    span_end=args.span_end,
                )
                result = {"evidence_id": evidence_id}
            elif args.command == "publish":
                result = await publication.enqueue_publication(db, actor=args.actor)
            elif args.command == "rebuild-snapshot":
                result = await publication.enqueue_snapshot_rebuild(db, actor=args.actor)
            elif args.command == "status":
                result = await review.graph_status(db)
            elif args.command == "publication-status":
                result = await publication.publication_status(db)
            elif args.command == "claim-job":
                result = await publication.claim_next_job(
                    db, owner=args.owner, lease_seconds=args.lease_seconds
                )
            elif args.command == "complete-job":
                await publication.complete_job(db, args.job, owner=args.owner)
                result = {"job_id": args.job, "status": "succeeded"}
            elif args.command == "fail-job":
                await publication.fail_job(
                    db,
                    args.job,
                    owner=args.owner,
                    error_code=args.code,
                    error_message=args.message,
                )
                result = {"job_id": args.job, "status": "failed"}
            else:
                report = await review.verify_graph(db)
                result = {"report": report, "ok": report.ok}
                exit_code = 0 if report.ok else 1
            await db.commit()
        except _DOMAIN_ERRORS as exc:
            await db.commit()
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 1
        except ValidationError as exc:
            await db.commit()
            print(
                json.dumps(
                    {"ok": False, "error": "登记文件不合法", "details": exc.errors()[:10]},
                    ensure_ascii=False,
                    default=str,
                )
            )
            return 1
        except OSError as exc:
            await db.commit()
            print(json.dumps({"ok": False, "error": f"文件读取失败：{exc}"}, ensure_ascii=False))
            return 1
    print(
        json.dumps(
            {"ok": True, "command": args.command, "result": _to_jsonable(result)},
            ensure_ascii=False,
            default=str,
        )
    )
    return exit_code


def _to_jsonable(value: object) -> object:
    """把 dataclass 结果（可能是嵌套结构）换成可直接 JSON 化的字典。"""

    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    return value


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(run_command(args)))


if __name__ == "__main__":
    main()
