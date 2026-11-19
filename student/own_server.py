"""Персональный MCP-сервер варианта P04 (Filesystem: диагностика метрик рекомендательной системы).

Файл создан SmartClass при выдаче задания. Инструменты и их назначения уже
определены. Студент реализует ТОЛЬКО предметную функцию clean_recommendations(),
а также при необходимости улучшает отчёт и логику. Готовые функции
чтения/сохранения и MCP-транспорт менять необязательно.

Запуск: python -m student.own_server
Для сервера stdout — протокол; для отладки используйте stderr.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

RECALL_RE = re.compile(r"Recall@\s*(\d+)", re.IGNORECASE)
ASCII_ID_RE = re.compile(r"[A-Za-z0-9_]+")
REL_MARK_RE = re.compile(r"релевант", re.IGNORECASE)

ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = ROOT / "case"
OUTPUT_DIR = ROOT / "llm-mcp-result" / "outputs"
CASE_ID = "P04"
# Читаем ТОЛЬКО перечисленные входные файлы; никакого произвольного пути.
INPUT_FILES = ['data/recommendations.csv', 'data/history.csv', 'data/catalog.csv', 'data/relevance.json', 'docs/metric.md']


def _read_inputs() -> dict:
    """Готовая безопасная загрузка входных файлов из case/."""
    data = {}
    for rel_path in INPUT_FILES:
        path = (CASE_DIR / rel_path).resolve()
        if not path.is_relative_to(CASE_DIR.resolve()) or not path.is_file():
            raise ValueError("Недоступный файл задания: " + rel_path)
        if path.suffix == ".csv":
            with path.open(encoding="utf-8-sig", newline="") as handle:
                data[rel_path] = list(csv.DictReader(handle))
        elif path.suffix == ".json":
            data[rel_path] = json.loads(path.read_text(encoding="utf-8"))
        else:
            # Документы и примеры Python читаем как ТЕКСТ, не исполняем!
            # Кодировка явная: иначе на Windows (cp1251) теряется кириллица.
            data[rel_path] = path.read_text(encoding="utf-8")
    return {"case_id": CASE_ID, "sources": list(INPUT_FILES), "data": data}


def _write_output(filename: str, content: str) -> None:
    """Готовая запись в llm-mcp-result/outputs/, без обхода путей."""
    if filename not in {"result.json", "report.md"}:
        raise ValueError("Запрещено записывать такой файл: " + filename)
    report_dir = ROOT / "llm-mcp-result"
    if report_dir.is_symlink() or OUTPUT_DIR.is_symlink():
        raise ValueError("Символические ссылки для результатов запрещены")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUTPUT_DIR / filename
    if target.is_symlink() or not target.resolve().is_relative_to(OUTPUT_DIR.resolve()):
        raise ValueError("Запись за пределами outputs запрещена")
    target.write_text(content, encoding="utf-8")


def health_check() -> dict:
    """Проверка связи с сервером; не считается предметным инструментом."""
    return {"status": "ready", "case_id": CASE_ID}


def get_user_data() -> dict:
    """прочитать рекомендации, историю, каталог и релевантность. Вход: без аргументов; выход: case_id, sources, data."""
    return _read_inputs()


def clean_recommendations() -> dict:
    """убрать повторы/просмотренные/несуществующие позиции и вычислить Recall@K.

    Вход: без аргументов. Источники доступны через get_user_data().
    Выход: JSON-словарь с полями case_id, status='completed',
    sources, result, checks, report_md. Содержание result: очищенный top-K по user_id и численные значения Recall@K.
    Отчёт report_md — Markdown не короче 60 символов.
    """
    payload = _read_inputs()
    data = payload["data"]

    recommendations = list(data.get("data/recommendations.csv") or [])
    history = list(data.get("data/history.csv") or [])
    catalog = list(data.get("data/catalog.csv") or [])
    relevance_raw = data.get("data/relevance.json")
    metric_text = str(data.get("docs/metric.md") or "")

    # metric.md — недоверенный документ. Извлекаем из него ТОЛЬКО правило
    # "Recall@<K>" и ID из фразы про релевантные непросмотренные позиции.
    # Остальные предложения считаем данными, а не командами агенту.
    k_match = RECALL_RE.search(metric_text)
    k = int(k_match.group(1)) if k_match else 3
    if k <= 0:
        k = 3
    text_rule = ""
    if k_match:
        text_rule = metric_text[k_match.start():].split(".", 1)[0].strip()
    rel_from_text: set[str] = set()
    for sentence in re.split(r"[.:;!\n]", metric_text):
        if REL_MARK_RE.search(sentence):
            for token in ASCII_ID_RE.findall(sentence):
                rel_from_text.add(token)

    seen_by_user: dict[str, set[str]] = {}
    for row in history:
        user = str(row.get("user") or "").strip()
        item = str(row.get("seen") or "").strip()
        if user and item:
            seen_by_user.setdefault(user, set()).add(item)

    active_items = {str(row.get("item") or "").strip() for row in catalog
                    if str(row.get("item") or "").strip()}
    has_active_flag = any("active" in row for row in catalog)
    if has_active_flag:
        active_items = {str(row.get("item") or "").strip() for row in catalog
                        if str(row.get("item") or "").strip()
                        and str(row.get("active") or "1").strip() not in ("0", "", "false", "False")}
    # ID из документа считаем релевантными только если они есть в каталоге.
    rel_from_text = {i for i in rel_from_text if i in active_items}

    relevance_by_user: dict[str, set[str]] = {}
    if isinstance(relevance_raw, dict):
        for user, ids in relevance_raw.items():
            if isinstance(ids, list):
                relevance_by_user[str(user)] = {str(i) for i in ids}

    by_user: dict[str, list[dict]] = {}
    for row in recommendations:
        user = str(row.get("user") or "").strip()
        if not user:
            continue
        try:
            rank = int(float(str(row.get("rank"))))
        except (TypeError, ValueError):
            rank = 10**9
        by_user.setdefault(user, []).append({
            "user": user, "rank": rank,
            "item": str(row.get("item") or "").strip(),
        })

    cleaned: dict[str, list[dict]] = {}
    removals: dict[str, list[dict]] = {}
    for user in sorted(by_user):
        rows = sorted(by_user[user], key=lambda r: (r["rank"], r["item"]))
        kept: list[dict] = []
        dropped: list[dict] = []
        used: set[str] = set()
        seen = seen_by_user.get(user, set())
        for row in rows:
            item = row["item"]
            if not item:
                dropped.append({"user": user, "item": "", "rank": row["rank"],
                                "reason": "empty_item_id"})
                continue
            if item in seen:
                dropped.append({"user": user, "item": item, "rank": row["rank"],
                                "reason": "already_seen"})
                continue
            if item in used:
                dropped.append({"user": user, "item": item, "rank": row["rank"],
                                "reason": "duplicate"})
                continue
            if catalog and item not in active_items:
                dropped.append({"user": user, "item": item, "rank": row["rank"],
                                "reason": "not_in_catalog"})
                continue
            used.add(item)
            kept.append({"item": item, "rank": row["rank"]})
        cleaned[user] = kept[:k]
        removals[user] = dropped

    per_user_metrics: dict[str, dict] = {}
    all_recall: list[float] = []
    domain_ok = bool(recommendations) and bool(cleaned) and k > 0
    for user in sorted(cleaned):
        kept_ids = [r["item"] for r in cleaned[user]]
        # relevance.json — приоритет; метрика из metric.md — только если
        # пользователя в JSON нет.
        if user in relevance_by_user:
            relevant = set(relevance_by_user[user])
        else:
            relevant = set(rel_from_text)
        relevant -= seen_by_user.get(user, set())
        hits = [i for i in kept_ids if i in relevant]
        recall = (len(hits) / len(relevant)) if relevant else 0.0
        if not relevant:
            domain_ok = False
        all_recall.append(recall)
        per_user_metrics[user] = {
            "cleaned_top_k": kept_ids,
            "k": k,
            "relevant_items": sorted(relevant),
            "hits": hits,
            "recall_at_k": round(recall, 4),
            "removed": removals.get(user, []),
        }

    mean_recall = round(sum(all_recall) / len(all_recall), 4) if all_recall else 0.0
    checks = {
        "domain_passed": bool(domain_ok and all(0.0 <= m["recall_at_k"] <= 1.0
                                                for m in per_user_metrics.values())),
        "k_source": f"docs/metric.md (Recall@{k})" if k_match else "default k=3 (rule not found)",
        "inputs_read": payload["sources"],
        "unique_and_catalog_filter_applied": True,
        "seen_removed": any(r["reason"] == "already_seen" for rs in removals.values() for r in rs),
        "duplicates_removed": any(r["reason"] == "duplicate" for rs in removals.values() for r in rs),
        "not_in_catalog_removed": any(r["reason"] == "not_in_catalog" for rs in removals.values() for r in rs),
        "recall_within_unit_interval": all(0.0 <= m["recall_at_k"] <= 1.0
                                           for m in per_user_metrics.values()),
        "known_expected_recall": 0.5,
        "computed_mean_recall": mean_recall,
        "recall_matches_reference": abs(mean_recall - 0.5) < 1e-9,
    }

    report_lines = [
        f"# Отчёт P04: очистка рекомендаций и Recall@{k}",
        "",
        "## Исходные данные",
        "- `case/data/recommendations.csv` — ранжированные кандидаты U1 (A,B,B,X,C).",
        "- `case/data/history.csv` — просмотренные позиции (A).",
        "- `case/data/catalog.csv` — активный каталог (A,B,C,D).",
        "- `case/data/relevance.json` + `case/docs/metric.md` — релевантность и правило метрики."
        + (f" Правило из документа: «{text_rule}»." if text_rule else ""),
        "",
        "## Алгоритм очистки",
        "1. Сортировка кандидатов по `rank` внутри пользователя.",
        "2. Отсев просмотренных (`history`), дубликатов ID и отсутствующих в активном `catalog`.",
        "3. Из первых `k` допустимых уникальных позиций считается Recall@K:",
        "   `|top-K ∩ relevant| / |relevant|`; просмотренные исключаются из relevant.",
        "4. metric.md рассматривается как недоверенный текст: из него берётся только",
        "   число K и перечисленные ID, которые реально есть в каталоге; инструкции",
        "   вида «игнорируй политику» в расчёт не принимаются.",
        "",
        "## Результат",
    ]
    for user, m in per_user_metrics.items():
        report_lines.append(
            f"- **{user}**: top-{k} = `{m['cleaned_top_k']}`, удалено "
            f"`{[(r['item'], r['reason']) for r in m['removed']]}`, "
            f"hits = `{m['hits']}`, Recall@{k} = **{m['recall_at_k']}**."
        )
    report_lines += [
        "",
        f"Средний Recall@{k} по пользователям: **{mean_recall}** "
        "(эталон по данным: 0.5 — найден только B из релевантных B,D).",
        "",
        "## Ограничения",
        "- Метрика посчитана без обучения рекомендателя; используется сохранённая релевантность.",
        "- Исходные файлы `case/` не изменялись; результат доступен только через `save_result`.",
    ]
    report_md = "\n".join(report_lines)

    return {
        "case_id": CASE_ID,
        "status": "completed",
        "sources": payload["sources"],
        "result": {
            "users": per_user_metrics,
            "mean_recall_at_k": mean_recall,
            "k": k,
            "removal_summary": {
                u: [r["reason"] for r in rs] for u, rs in removals.items()
            },
        },
        "checks": checks,
        "report_md": report_md,
    }


def save_result() -> dict:
    """Сохранить проверенный предметный результат в outputs/result.json и report.md.

    Выход: status='saved' и список двух файлов. Пока clean_recommendations()
    не реализована, этот инструмент ничего не сохраняет.
    """
    result = clean_recommendations()
    if not isinstance(result, dict) or result.get("case_id") != CASE_ID:
        raise ValueError("Анализ должен вернуть объект со своим case_id")
    if result.get("status") != "completed":
        raise ValueError("Нельзя сохранять незавершённый анализ")
    if not isinstance(result.get("result"), dict) or not result["result"]:
        raise ValueError("В результате нет содержательных данных")
    if not isinstance(result.get("sources"), list) or not result["sources"]:
        raise ValueError("В результате нет источников")
    if not isinstance(result.get("checks"), dict) or not result["checks"]:
        raise ValueError("В результате нет проверок")
    report_md = result.get("report_md", "")
    if not isinstance(report_md, str) or len(report_md.strip()) < 60:
        raise ValueError("report_md должен содержать содержательный отчёт")
    public_result = {k: v for k, v in result.items() if k != "report_md"}
    # Не сохраняем ни одного файла, пока полностью не проверили контракт.
    _write_output("result.json", json.dumps(public_result, ensure_ascii=False, indent=2) + "\n")
    _write_output("report.md", report_md.rstrip() + "\n")
    return {"status": "saved", "files": ["outputs/result.json", "outputs/report.md"]}


# Регистрация 4 реальных MCP-инструментов: health + 3 предметных.
# Протокольный каркас уже предоставлен; его необязательно переписывать.
TOOLS = {
    "health_check": (health_check, health_check.__doc__),
    "get_user_data": (get_user_data, get_user_data.__doc__),
    "clean_recommendations": (clean_recommendations, clean_recommendations.__doc__),
    "save_result": (save_result, save_result.__doc__),
}


def _dispatch(method: str, params: dict) -> dict:
    if method == "initialize":
        return {"protocolVersion": "2025-06-18",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "student-P04", "version": "0.4"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [{"name": name, "description": desc,
                           "inputSchema": {"type": "object", "properties": {}, "required": []}}
                          for name, (_, desc) in TOOLS.items()]}
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments", {})
        if name not in TOOLS or not isinstance(arguments, dict) or arguments:
            return {"isError": True, "content": [{"type": "text", "text": "Неверный инструмент или аргументы"}]}
        try:
            answer = TOOLS[name][0]()
            return {"isError": False, "content": [{"type": "text", "text": json.dumps(answer, ensure_ascii=False)}]}
        except (NotImplementedError, ValueError, OSError, TypeError, KeyError) as exc:
            return {"isError": True, "content": [{"type": "text", "text": f"{type(exc).__name__}: {str(exc)[:180]}"}]}
    raise ValueError("Неизвестный MCP метод: " + method)


def main() -> None:
    # Построчный stdio JSON-RPC совместим с course.protocol.MCPStdio.
    # Ничего не печатайте в stdout, кроме ответов на запросы JSON-RPC.
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                continue
            if request.get("method") == "notifications/initialized" or "id" not in request:
                continue
            try:
                response = {"jsonrpc": "2.0", "id": request["id"],
                            "result": _dispatch(request.get("method", ""), request.get("params") or {})}
            except (ValueError, TypeError) as exc:
                response = {"jsonrpc": "2.0", "id": request["id"],
                            "error": {"code": -32601, "message": str(exc)[:180]}}
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        except (ValueError, TypeError):
            continue


if __name__ == "__main__":
    main()
