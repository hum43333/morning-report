"""
generate_report.py
매일 새벽 4시에 실행되어 report.json을 생성합니다.
"""

import json
import os
import datetime
import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events

# ── 설정 ──────────────────────────────────────────────
# 한국/일본 표준시 (UTC+9). 둘 다 같은 시간대지만 명확하게 KST/JST 둘 다 표시.
KST = ZoneInfo("Asia/Seoul")
now       = datetime.datetime.now(KST)
today     = now.date()
yesterday = today - datetime.timedelta(days=1)
tomorrow  = today + datetime.timedelta(days=1)

WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY", "")

ICAL_URLS = [
    "https://p33-caldav.icloud.com/published/2/MTAwMzk4NDcwNTEwMDM5OIKMqbxDECSm4-w6pcPcOCIVP58eGmQm8cjZa9KDDBF9vv8SoApAB7gMPuYjpGnH98fB8YWpMvUQeizQXhsRZYU",
    "https://p33-caldav.icloud.com/published/2/MTAwMzk4NDcwNTEwMDM5OIKMqbxDECSm4-w6pcPcOCJrKUsO_AW5w6v0v7oNHYHd5WsV_bMsDk3ACrtnjpxRLabjLsx6CvWdC053Tr3Ss-g",
    "https://p33-caldav.icloud.com/published/2/MTAwMzk4NDcwNTEwMDM5OIKMqbxDECSm4-w6pcPcOCL-WdRUZNC9M2efypMusaAxOrdpLbYaR1k0kC7y_jLkePUEckPoFCXcbO9OSoe0tAQ",
    "https://p33-caldav.icloud.com/published/2/MTAwMzk4NDcwNTEwMDM5OIKMqbxDECSm4-w6pcPcOCIoHyRjBOE4G3iJ_M_buNvEZ002XGdl5_L-zSwB2nVANnvgPEFdRe6Br16WHVu4Ipc",
    "https://p33-caldav.icloud.com/published/2/MTAwMzk4NDcwNTEwMDM5OIKMqbxDECSm4-w6pcPcOCKfMnmOVmqGDC8rvy7RkR9ttHeHkOs1HcsaMSF6tViJlgCHQCsV2zJ1gSjmaCPg6Ow",
    "https://calendar.google.com/calendar/ical/ko.south_korea%23holiday%40group.v.calendar.google.com/public/basic.ics",
    "https://calendars.icloud.com/holidays/jp_ja.ics",
]

# ── 날씨 ──────────────────────────────────────────────
def get_weather():
    """OpenWeatherMap API로 오늘 아침/낮/저녁 날씨 가져오기 (나가노 기준)"""
    if not WEATHER_API_KEY:
        return {"morning": "날씨 API 키 없음", "afternoon": "", "evening": ""}
    try:
        url = (
            "https://api.openweathermap.org/data/2.5/forecast"
            f"?q=Nagano,JP&appid={WEATHER_API_KEY}&units=metric&lang=kr"
        )
        r = requests.get(url, timeout=10)
        data = r.json()

        targets = {"morning": 6, "afternoon": 12, "evening": 18}
        result = {}

        for key, target_hour in targets.items():
            best = None
            best_diff = 999
            for item in data.get("list", []):
                dt = datetime.datetime.fromtimestamp(item["dt"], tz=KST)
                if dt.date() != today:
                    continue
                diff = abs(dt.hour - target_hour)
                if diff < best_diff:
                    best_diff = diff
                    best = item

            if best:
                desc = best["weather"][0]["description"]
                temp = round(best["main"]["temp"])
                main = best["weather"][0]["main"].lower()
                if "rain" in main or "drizzle" in main or "thunderstorm" in main:
                    label = "비"
                elif "cloud" in main:
                    label = "흐림"
                elif "snow" in main:
                    label = "눈"
                else:
                    label = "맑음"
                result[key] = f"{label} ({desc}, {temp}°C)"
            else:
                result[key] = "정보 없음"

        return result
    except Exception as e:
        return {"morning": f"날씨 오류: {e}", "afternoon": "", "evening": ""}


# ── 성무일도 ───────────────────────────────────────────
def get_liturgy():
    """catholic.or.kr 성무일도 아침기도 본문 추출."""
    try:
        date_str = today.strftime("%Y-%m-%d")
        headers = {"User-Agent": "Mozilla/5.0"}
        url = (
            f"https://maria.catholic.or.kr/mi_pr/sungmu/sungmu.asp"
            f"?menu=sungmu&sunseo=1&gomonth={date_str}&stype=mo"
        )
        r = requests.get(url, headers=headers, timeout=15)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        full_text = soup.get_text(separator="\n")
        lines = [l.strip() for l in full_text.splitlines()]

        start_idx = None
        for i, line in enumerate(lines):
            if "날 구하소서" in line:
                start_idx = i
                break

        if start_idx is None:
            tables = soup.find_all("table")
            fallback = []
            for table in tables:
                t = table.get_text(separator="\n")
                if "하느님" in t or "찬미" in t or "시편" in t:
                    for line in t.splitlines():
                        line = line.strip()
                        if line:
                            fallback.append(line)
            return "\n".join(fallback) if fallback else "아침기도 본문을 찾지 못했습니다."

        found_pagen = False
        end_idx = len(lines)
        for i in range(start_idx + 1, len(lines)):
            if "파견" in lines[i]:
                found_pagen = True
            if found_pagen and any(kw in lines[i] for kw in [
                "이용약관", "ⓒ GoodNews", "서울대교구", "goodnews@",
                "매일미사", "가톨릭기도서", "7성사",
                "(구)성경쓰기", "미사/기도서", "말씀나누기", "성경책갈피", "내 교구"
            ]):
                end_idx = i
                break
            if not found_pagen and any(kw in lines[i] for kw in [
                "이용약관", "ⓒ GoodNews", "서울대교구", "goodnews@",
                "(구)성경쓰기", "미사/기도서"
            ]):
                end_idx = i
                break

        result = []
        for line in lines[start_idx:end_idx]:
            if line and not any(bad in line for bad in [
                "goodnews", "catholic.or.kr", "이용약관",
                "개인정보", "ⓒ", "글자크기", "quick"
            ]):
                result.append(line)

        return "\n".join(result) if result else "아침기도 본문을 찾지 못했습니다."
    except Exception as e:
        return f"성무일도 오류: {e}"


# ── 오늘의 복음 ────────────────────────────────────────
def get_gospel(target_date=None):
    """catholic.or.kr 미사 페이지에서 독서/복음 스크래핑."""
    import re
    if target_date is None:
        target_date = today
    result = {"reading1": "", "reading2": "", "gospel": ""}
    try:
        date_str = target_date.strftime("%Y-%m-%d")
        url = (
            f"https://maria.catholic.or.kr/mi_pr/missa/missa.asp"
            f"?menu=missa&gomonth={date_str}&missatype=DA"
        )
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=15)
        r.encoding = r.apparent_encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")

        raw = soup.get_text(separator="\n")
        lines = [l.strip() for l in raw.splitlines() if l.strip()]

        date_pattern = re.compile(r"\d{4}년 \d+월 \d+일")
        target_year  = target_date.strftime("%Y년")
        target_month = str(target_date.month) + "월"
        target_day   = str(target_date.day) + "일"
        body_start = 0
        for i, line in enumerate(lines):
            if (date_pattern.search(line) and target_year in line
                    and target_month in line and target_day in line):
                body_start = i
                break
        else:
            for i, line in enumerate(lines):
                if date_pattern.search(line):
                    body_start = i
                    break

        lines = lines[body_start:]

        sections = {"reading1": [], "reading2": [], "gospel": []}
        current = None
        reading1_done = False

        for line in lines:
            if "제1독서" in line and current is None and not reading1_done:
                current = "reading1"
                sections["reading1"].append(line)
                continue
            if "제2독서" in line and current is None:
                current = "reading2"
                sections["reading2"].append(line)
                continue
            if ("✠" in line or "거룩한 복음입니다" in line) and current != "gospel":
                current = "gospel"
                sections["gospel"].append(line)
                continue

            if current == "reading1":
                if "주님의 말씀입니다" in line or "하느님 감사합니다" in line:
                    sections["reading1"].append(line)
                    current = None
                    reading1_done = True
                elif any(kw in line for kw in ["화답송", "알렐루야", "복음 환호송", "제2독서"]):
                    current = None
                    reading1_done = True
                else:
                    sections["reading1"].append(line)
            elif current == "reading2":
                if "주님의 말씀입니다" in line or "하느님 감사합니다" in line:
                    sections["reading2"].append(line)
                    current = None
                elif any(kw in line for kw in ["화답송", "알렐루야", "복음 환호송"]):
                    current = None
                else:
                    sections["reading2"].append(line)
            elif current == "gospel":
                sections["gospel"].append(line)
                if "그리스도님, 찬미합니다" in line:
                    current = None
                    break

        result["reading1"] = "\n".join(sections["reading1"])
        result["reading2"] = "\n".join(sections["reading2"])
        result["gospel"]   = "\n".join(sections["gospel"])

    except Exception as e:
        result["reading1"] = f"복음 오류: {e}"
    return result


# ── iCloud / Google 캘린더 ─────────────────────────────
def _fetch_all_calendars():
    """모든 캘린더 URL에서 ical 데이터를 받아 파싱한 Calendar 객체 리스트를 반환."""
    headers = {"User-Agent": "Mozilla/5.0"}
    calendars = []
    for ical_url in ICAL_URLS:
        try:
            r = requests.get(ical_url, headers=headers, timeout=15)
            r.encoding = "utf-8"
            cal = icalendar.Calendar.from_ical(r.text)
            calendars.append(cal)
        except Exception as e:
            print(f"캘린더 URL 오류: {ical_url[:60]}... → {e}")
    return calendars


def _format_event(component, target_date):
    """ical 이벤트 컴포넌트 1개를 '12:00 제목' 또는 '종일 제목' 형태로 변환."""
    summary = str(component.get("SUMMARY", "(제목 없음)"))
    dtstart = component.get("DTSTART")
    if dtstart is None:
        return f"- {summary}"

    value = dtstart.dt

    # 종일 일정: dtstart가 date 타입 (시간 없음)
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return f"종일 {summary}"

    # 시간 있는 일정: datetime 타입
    if isinstance(value, datetime.datetime):
        # tzinfo가 없으면 한국 시간으로 간주, 있으면 한국 시간으로 변환
        if value.tzinfo is None:
            local = value.replace(tzinfo=KST)
        else:
            local = value.astimezone(KST)
        # 변환 후 날짜가 target_date와 다르면 종일/넘치는 일정으로 처리
        if local.date() != target_date:
            return f"종일 {summary}"
        return f"{local.strftime('%H:%M')} {summary}"

    return f"- {summary}"


def get_calendar_events(date: datetime.date) -> list:
    """여러 ical 캘린더에서 해당 날짜의 일정(반복 일정 포함)을 가져온다."""
    try:
        calendars = _fetch_all_calendars()
        if not calendars:
            return ["일정 없음"]

        # 한국 시간 기준 그날의 0시 ~ 다음 날 0시 범위
        start_dt = datetime.datetime.combine(date, datetime.time(0, 0), tzinfo=KST)
        end_dt   = start_dt + datetime.timedelta(days=1)

        seen = set()  # (시작시각문자열, 제목) 중복 제거용
        result = []

        for cal in calendars:
            try:
                events = recurring_ical_events.of(cal).between(start_dt, end_dt)
            except Exception as e:
                print(f"이벤트 전개 오류: {e}")
                continue

            for ev in events:
                line = _format_event(ev, date)
                key = line  # 동일 표시 줄을 중복으로 보고 합침
                if key in seen:
                    continue
                seen.add(key)
                result.append(line)

        result.sort()
        print(f"{date} 일정 {len(result)}개")
        return result if result else ["일정 없음"]

    except Exception as e:
        return [f"캘린더 오류: {e}"]


# ── 신문 RSS ───────────────────────────────────────────
def get_news(paper_key: str) -> list:
    """각 신문사 RSS에서 기사 제목 3개 추출"""
    rss_urls = {
        "hankyoreh": "https://www.hani.co.kr/rss/",
        "chosun":    "https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml",
        "jtbc":      "https://fs.jtbc.co.kr/RSS/newsflash.xml",
        "donga":     "https://rss.donga.com/total.xml",
    }
    url = rss_urls.get(paper_key)
    if not url:
        return ["RSS 주소 없음"]
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.content, "xml")
        items = soup.find_all("item")[:3]
        return [item.find("title").get_text(strip=True) for item in items if item.find("title")]
    except Exception as e:
        return [f"오류: {e}"]


# ── 안경(Web Scope)용 HTML 생성 ──────────────────────────
# Web Scope는 페이지의 HTML 구조에서 "기사 목록"을 찾아 추출하는 방식.
# Gigazine처럼 작동하려면:
#   - 메인 페이지: 반복되는 기사 카드 구조 (h2 > a + 날짜 + 카테고리)
#   - 각 기사: 별도 URL의 별도 HTML 파일

def html_escape(s):
    """HTML 특수문자 escape."""
    if s is None:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def text_to_html_paragraphs(text):
    """줄바꿈이 들어있는 일반 텍스트를 <p>로 감싼 HTML로 변환."""
    if not text:
        return "<p>정보 없음</p>"
    paragraphs = []
    current = []
    for line in text.split("\n"):
        if line.strip() == "":
            if current:
                paragraphs.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        paragraphs.append("\n".join(current))
    if not paragraphs:
        return "<p>정보 없음</p>"
    return "\n".join(
        "<p>" + html_escape(p).replace("\n", "<br>") + "</p>"
        for p in paragraphs
    )


def write_article_page(filename, title, body_html, date_str, category):
    """안경용 개별 기사 HTML 파일 한 개 작성."""
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html_escape(title)}</title>
</head>
<body>
<article>
<h1>{html_escape(title)}</h1>
<p><time datetime="{html_escape(date_str)}">{html_escape(date_str)}</time>
&nbsp;<span class="category">{html_escape(category)}</span></p>
{body_html}
</article>
</body>
</html>
"""
    os.makedirs("glasses", exist_ok=True)
    with open(f"glasses/{filename}", "w", encoding="utf-8") as f:
        f.write(html)


def write_glasses_index(report, articles):
    """안경용 메인 목록 페이지 (기사 카드 반복 구조).

    articles: [(filename, title, category), ...]
    """
    date_str = report["date"]
    items_html = []
    for fname, title, category in articles:
        items_html.append(f"""
<article class="entry">
<h2><a href="{html_escape(fname)}">{html_escape(title)}</a></h2>
<p><time datetime="{html_escape(date_str)}">{html_escape(date_str)}</time>
&nbsp;<a href="{html_escape(fname)}" class="category">{html_escape(category)}</a></p>
</article>
""".strip())

    items_block = "\n\n".join(items_html)

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>모닝 리포트 {html_escape(date_str)}</title>
<meta name="description" content="모닝 리포트 {html_escape(date_str)}">
</head>
<body>
<header>
<h1>모닝 리포트</h1>
<p>{html_escape(date_str)}</p>
</header>

<main>
{items_block}
</main>

<footer>
<p>생성: {html_escape(report.get("generated_at", ""))}</p>
</footer>
</body>
</html>
"""
    os.makedirs("glasses", exist_ok=True)
    with open("glasses/index.html", "w", encoding="utf-8") as f:
        f.write(html)


def build_glasses_pages(report):
    """report 딕셔너리로부터 안경용 HTML 6개 + 목록 페이지 1개를 만든다."""
    date_str = report["date"]

    # ── 1. 날씨 ──
    w = report.get("weather", {})
    if isinstance(w, str):
        weather_body = f"<p>{html_escape(w)}</p>"
    else:
        parts = []
        for key, label in [("morning", "아침"), ("afternoon", "낮"), ("evening", "저녁")]:
            val = (w or {}).get(key) or "정보 없음"
            parts.append(f"<h2>{html_escape(label)}</h2><p>{html_escape(val)}</p>")
        weather_body = "\n".join(parts)
    write_article_page("01-weather.html", "오늘의 날씨", weather_body, date_str, "날씨")

    # ── 2. 성무일도 ──
    liturgy_body = text_to_html_paragraphs(report.get("liturgy", ""))
    write_article_page("02-liturgy.html", "오늘의 성무일도", liturgy_body, date_str, "기도")

    # ── 3. 오늘의 복음 ──
    def gospel_to_html(g):
        if not g:
            return "<p>정보 없음</p>"
        parts = []
        if g.get("reading1"):
            parts.append("<h2>제1독서</h2>" + text_to_html_paragraphs(g["reading1"]))
        if g.get("reading2"):
            parts.append("<h2>제2독서</h2>" + text_to_html_paragraphs(g["reading2"]))
        if g.get("gospel"):
            parts.append("<h2>복음</h2>" + text_to_html_paragraphs(g["gospel"]))
        return "\n".join(parts) if parts else "<p>정보 없음</p>"

    write_article_page("03-gospel.html", "오늘의 복음",
                       gospel_to_html(report.get("gospel")), date_str, "복음")

    # ── 4. 내일의 복음 ──
    write_article_page("04-gospel-tomorrow.html", "내일의 복음",
                       gospel_to_html(report.get("gospel_tomorrow")), date_str, "복음")

    # ── 5. 일정 ──
    cal = report.get("calendar", {}) or {}
    cal_parts = []
    for key, label in [("yesterday", "어제"), ("today", "오늘"), ("tomorrow", "내일")]:
        events = [e for e in (cal.get(key) or []) if e and e.strip() != "일정 없음"]
        cal_parts.append(f"<h2>{html_escape(label)}</h2>")
        if events:
            cal_parts.append("<ul>")
            for e in events:
                cal_parts.append(f"<li>{html_escape(e)}</li>")
            cal_parts.append("</ul>")
        else:
            cal_parts.append("<p>일정 없음</p>")
    write_article_page("05-calendar.html", "일정", "\n".join(cal_parts), date_str, "일정")

    # ── 6. 신문 ──
    news = report.get("news", {}) or {}
    paper_names = {
        "hankyoreh": "한겨레",
        "chosun":    "조선일보",
        "jtbc":      "JTBC",
        "joongang":  "JTBC",
        "donga":     "동아일보",
    }
    news_parts = []
    seen = set()
    for key in ["hankyoreh", "chosun", "jtbc", "joongang", "donga"]:
        if key not in news:
            continue
        display = paper_names.get(key, key)
        if display in seen:
            continue
        seen.add(display)
        articles_list = news.get(key) or []
        news_parts.append(f"<h2>{html_escape(display)}</h2>")
        if articles_list:
            news_parts.append("<ol>")
            for t in articles_list:
                news_parts.append(f"<li>{html_escape(t)}</li>")
            news_parts.append("</ol>")
        else:
            news_parts.append("<p>정보 없음</p>")
    write_article_page("06-news.html", "주요 신문 기사",
                       "\n".join(news_parts), date_str, "뉴스")

    # ── 메인 목록 페이지 ──
    articles = [
        ("01-weather.html",         "오늘의 날씨",       "날씨"),
        ("02-liturgy.html",         "오늘의 성무일도",   "기도"),
        ("03-gospel.html",          "오늘의 복음",       "복음"),
        ("04-gospel-tomorrow.html", "내일의 복음",       "복음"),
        ("05-calendar.html",        "일정",              "일정"),
        ("06-news.html",            "주요 신문 기사",    "뉴스"),
    ]
    write_glasses_index(report, articles)
    print("glasses/ 폴더에 안경용 HTML 7개 생성 완료!")


# ── 메인 ───────────────────────────────────────────────
def main():
    print("리포트 생성 시작...")

    report = {
        "date":            today.strftime("%Y-%m-%d"),
        "generated_at":    now.strftime("%Y-%m-%d %H:%M"),
        "weather":         get_weather(),
        "liturgy":         get_liturgy(),
        "gospel":          get_gospel(today),
        "gospel_tomorrow": get_gospel(tomorrow),
        "calendar": {
            "yesterday": get_calendar_events(yesterday),
            "today":     get_calendar_events(today),
            "tomorrow":  get_calendar_events(tomorrow),
        },
        "news": {
            "hankyoreh": get_news("hankyoreh"),
            "chosun":    get_news("chosun"),
            "jtbc":      get_news("jtbc"),
            "donga":     get_news("donga"),
        }
    }

    with open("report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("report.json 생성 완료!")

    # 안경(Web Scope)용 HTML 생성
    try:
        build_glasses_pages(report)
    except Exception as e:
        print(f"안경용 HTML 생성 오류: {e}")


if __name__ == "__main__":
    main()
