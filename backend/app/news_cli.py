"""健康资讯运维 CLI（前台运行、跑完即退出；**不注册任何自启动、不落计划任务**）。

用法：`python -m app.news_cli --help`。CLI 直接读写开发库，属于运营人员的显式动作，
因此 `--refresh`（manual）不受 `news_portal_enabled` 影响；`--enable` 必须同时给
`--license-note`，把「谁/何时/核对了什么」写进来源记录。
"""

import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy import delete, func, select

from app.db.session import SessionLocal
from app.models.news import NewsItem, NewsRefreshRun, NewsSource
from app.services.news import repository
from app.services.news.catalog import BLOCKED_SOURCES, CATALOG, get_spec
from app.services.news.refresh import refresh_sources


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.news_cli", description="健康资讯运维 CLI（前台）"
    )
    parser.add_argument("--catalog", action="store_true", help="列出代码内登记的候选来源")
    parser.add_argument("--list", action="store_true", help="列出库内来源与状态")
    parser.add_argument("--enable", metavar="SOURCE_ID", help="启用来源（必须配 --license-note）")
    parser.add_argument("--disable", metavar="SOURCE_ID", help="停用来源并移除其条目")
    parser.add_argument(
        "--delete-source", metavar="SOURCE_ID", help="彻底删除来源行及其条目（试跑清理用）"
    )
    parser.add_argument(
        "--purge-runs", action="store_true", help="清除刷新运行记录（不影响来源与条目）"
    )
    parser.add_argument("--license-note", default="", help="许可核对结论，写入来源记录")
    parser.add_argument("--refresh", action="store_true", help="执行一轮抓取（会访问外网）")
    parser.add_argument("--source", action="append", default=None, help="只刷新指定来源，可重复")
    parser.add_argument("--limit", type=int, default=None, help="每个来源最多收录条数")
    parser.add_argument("--trigger", choices=("manual", "auto"), default="manual")
    parser.add_argument(
        "--items", metavar="CATEGORY", default=None, help="查看某分类在展示期的条目"
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    async with SessionLocal() as db:
        if args.catalog:
            for spec in CATALOG.values():
                print(
                    f"[可启用] {spec.id}  {spec.name} / {spec.organization} / "
                    f"{','.join(spec.category_scope)}"
                )
                print(f"          许可记录：{spec.license_note}")
            for source_id, reason in BLOCKED_SOURCES.items():
                print(f"[不可自动读取] {source_id}：{reason}")
            return 0

        if args.enable:
            spec = get_spec(args.enable)
            if spec is None:
                print(
                    f"拒绝启用：{args.enable} 不在可自动读取的候选里。"
                    "用 --catalog 查看，障碍原因见 catalog.BLOCKED_SOURCES。"
                )
                return 2
            if not args.license_note.strip():
                print("拒绝启用：必须用 --license-note 记录许可核对结论（谁/何时/结论）。")
                return 2
            source = await db.get(NewsSource, spec.id)
            if source is None:
                db.add(
                    NewsSource(
                        id=spec.id,
                        name=spec.name,
                        organization=spec.organization,
                        homepage_url=spec.homepage_url,
                        feed_url=spec.feed_url,
                        fetch_mode=spec.fetch_mode,
                        category_scope=list(spec.category_scope),
                        license_note=args.license_note.strip(),
                        enabled=True,
                    )
                )
            else:
                source.license_note = args.license_note.strip()
                source.enabled = True
            await db.commit()
            print(f"已启用 {spec.id}（enabled=true）。条目为空时门户显示空态，不伪造内容。")
            return 0

        if args.disable:
            source = await db.get(NewsSource, args.disable)
            if source is None:
                print(f"没有这个来源：{args.disable}")
                return 2
            source.enabled = False
            removed = await repository.withdraw_source_items(db, source_id=source.id)
            await db.commit()
            print(f"已停用 {args.disable}，并移除其条目 {removed} 条。")
            return 0

        if args.delete_source:
            source = await db.get(NewsSource, args.delete_source)
            if source is None:
                print(f"没有这个来源：{args.delete_source}")
                return 2
            removed = await repository.withdraw_source_items(db, source_id=source.id)
            await db.delete(source)
            await db.commit()
            print(f"已删除来源 {args.delete_source}（同时移除条目 {removed} 条）。")
            return 0

        if args.purge_runs:
            removed = await db.execute(delete(NewsRefreshRun))
            await db.commit()
            print(f"已清除刷新运行记录 {removed.rowcount or 0} 条（来源与条目未动）。")
            return 0

        if args.refresh:
            summary = await refresh_sources(
                db,
                now=datetime.now(UTC),
                trigger=args.trigger,
                source_ids=args.source,
                limit=args.limit,
            )
            await db.commit()
            print(
                f"更新日 {summary.update_day}  trigger={args.trigger}  "
                f"结果={summary.status}  run={summary.run_id}"
            )
            for item in summary.results:
                print(
                    f"  {item.source_id}: {item.status} err={item.error_code} "
                    f"抓取={item.fetched} 新增={item.inserted} 刷新={item.refreshed} "
                    f"重复={item.duplicate} 拒收={item.rejected}"
                )
            if summary.status == "skipped":
                print("  没有可刷新的启用来源（或当日自动运行已用过）。")
            return 0 if summary.status in ("succeeded", "partial") else 1

        if args.items:
            page = await repository.read_items(
                db,
                category=args.items,
                limit=10,
                offset=0,
                now=datetime.now(UTC),
            )
            print(f"分类 {args.items}：{page.total} 条在展示期")
            for item, source in page.rows:
                print(f"  - [{source.name}] {item.title}")
                print(
                    f"    {item.canonical_url}  发布={item.published_at or '未核实'}  "
                    f"获取={item.last_seen_at}  已审核={item.medical_reviewed}"
                )
            return 0

        if args.list:
            sources = (await db.execute(select(NewsSource).order_by(NewsSource.id))).scalars().all()
            if not sources:
                print("库内没有任何来源（门户显示「新闻源尚未接入」，这是正确状态）。")
            for source in sources:
                count = await db.scalar(
                    select(func.count())
                    .select_from(NewsItem)
                    .where(NewsItem.source_id == source.id)
                )
                print(
                    f"  {source.id}  enabled={source.enabled}  "
                    f"模式={source.fetch_mode}  条目={count}"
                )
                print(
                    f"    最后尝试={source.last_attempt_at}  最后成功={source.last_success_at}  "
                    f"最近错误={source.last_error_code}"
                )
            return 0

    print("没有任何动作；用 --help 查看用法。")
    return 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())