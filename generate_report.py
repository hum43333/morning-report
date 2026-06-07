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
# 성무일도 시간대별 stype 파라미터 (catholic.or.kr)
#   mo = 아침기도, ev = 저녁기도, ni = 끝기도
LITURGY_TYPES = {
    "morning": {"stype": "mo", "label": "아침기도"},
    "evening": {"stype": "ev", "label": "저녁기도"},
    "night":   {"stype": "ni", "label": "끝기도"},
}

# 각 stype이 만들어내는 페이지에서 "본문 테이블"의 첫 셀(헤더)에 들어 있는 이름.
# 평소: "아침기도" / "저녁기도" / "끝기도"
# 주일·대축일 전날(토요일 등): "제1저녁기도" / "제1저녁기도후 끝기도" 등 변형이 나옴.
# 본문 테이블을 식별할 때 이 후보들 중 하나가 첫 셀에 포함되는지 확인한다.
_LITURGY_TABLE_HEADERS = {
    "mo":  ["아침기도"],
    "ev":  ["저녁기도", "제1저녁기도", "제2저녁기도"],
    "ni":  ["끝기도", "제1저녁기도후 끝기도", "제2저녁기도후 끝기도"],
}


def _fetch_liturgy_one(target_date, stype, label):
    """성무일도 한 종류(아침/저녁/끝)의 본문을 추출 (테이블 구조 기반).

    catholic.or.kr 페이지는 각 기도 시간을 별도의 <table>로 담아 보낸다.
    표의 첫 셀에 기도 이름(예: "아침기도", "제1저녁기도")이 들어 있고,
    나머지 셀에 기도문 본문이 단락별로 들어 있다.
    이 함수는 첫 셀이 기도 이름과 일치하는 표를 찾아 셀별로 텍스트를 모은다.
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    url = (
        f"https://maria.catholic.or.kr/mi_pr/sungmu/sungmu.asp"
        f"?menu=sungmu&sunseo=1&gomonth={target_date.strftime('%Y-%m-%d')}&stype={stype}"
    )
    r = requests.get(url, headers=headers, timeout=15)
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")

    expected = _LITURGY_TABLE_HEADERS.get(stype, [label])

    # ── 1단계: 본문 테이블 찾기 ──
    # 첫 셀 텍스트가 기도 이름과 정확히 일치(또는 그 단어로 시작)하는 표를 찾는다.
    target = None
    for table in soup.find_all("table"):
        first_cell = table.find(["td", "th"])
        if not first_cell:
            continue
        first_text = first_cell.get_text(strip=True)
        if any(first_text == name or first_text.startswith(name) for name in expected):
            target = table
            break

    # 2단계(백업): 1단계에서 못 찾으면, 표 내용 앞부분에 기도 이름이 포함되어 있는지로 추정
    if target is None:
        for table in soup.find_all("table"):
            head = table.get_text(strip=True)[:80]  # 첫 80자만 검사
            if any(name in head for name in expected):
                target = table
                break

    if target is None:
        return f"{label} 본문을 찾지 못했습니다. (테이블 없음)"

    # ── 표에서 셀별로 텍스트 추출 ──
    # 직접 자식 <tr>만 가져와서 중첩 테이블의 영향을 최소화한다.
    rows = target.find_all("tr", recursive=False)
    if not rows:
        tbody = target.find("tbody", recursive=False)
        if tbody:
            rows = tbody.find_all("tr", recursive=False)
    if not rows:
        rows = target.find_all("tr")  # 최후의 수단

    blocks = []
    for row in rows:
        cells = row.find_all(["td", "th"], recursive=False)
        if not cells:
            cells = row.find_all(["td", "th"])
        for cell in cells:
            text = cell.get_text(separator="\n", strip=True)
            # 셀 안에서 빈 줄 제거, 양옆 공백 정리
            text_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if text_lines:
                blocks.append("\n".join(text_lines))

    if not blocks:
        return f"{label} 본문이 비어 있습니다."

    return "\n\n".join(blocks)


def get_liturgy(kind="morning", target_date=None):
    """성무일도 본문 추출 (실패/짧은 결과 시 자동 재시도).

    kind: "morning"(아침기도) / "evening"(저녁기도) / "night"(끝기도)
    target_date: 대상 날짜 (기본값 = 오늘)

    사이트가 일시적으로 빈 페이지나 짧은 응답을 줄 수 있어서,
    결과가 200자 미만이면 잠시 기다렸다가 최대 3번까지 재시도한다.
    """
    import time
    if target_date is None:
        target_date = today
    cfg = LITURGY_TYPES.get(kind, LITURGY_TYPES["morning"])

    MIN_LENGTH = 200          # 이보다 짧으면 실패로 간주
    MAX_TRIES  = 3            # 최대 시도 횟수
    WAIT_SEC   = 5            # 재시도 전 대기 시간(초)

    last_result = ""
    last_error  = None
    for attempt in range(1, MAX_TRIES + 1):
        try:
            result = _fetch_liturgy_one(target_date, cfg["stype"], cfg["label"])
            last_result = result
            # 본문이 충분히 길면 성공
            if result and len(result) >= MIN_LENGTH and "찾지 못했습니다" not in result:
                if attempt > 1:
                    print(f"{cfg['label']}: {attempt}번째 시도에서 성공 ({len(result)}자)")
                return result
            # 짧으면 재시도
            print(f"{cfg['label']}: {attempt}번째 시도 결과가 짧음 ({len(result)}자), "
                  f"{WAIT_SEC}초 후 재시도")
        except Exception as e:
            last_error = e
            print(f"{cfg['label']}: {attempt}번째 시도 예외 - {e}")
        if attempt < MAX_TRIES:
            time.sleep(WAIT_SEC)

    # 모두 실패한 경우: 마지막 결과(짧더라도)를 반환, 아예 없으면 오류 메시지
    if last_result:
        print(f"{cfg['label']}: {MAX_TRIES}번 모두 짧음, 마지막 결과 사용")
        return last_result
    return f"{cfg['label']} 오류: {last_error}" if last_error else f"{cfg['label']} 본문을 찾지 못했습니다."


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





# ── 안경(Web Reader)용 HTML 생성 ──────────────────────────
# Web Reader는 r.jina.ai 같은 본문 추출기로 페이지 본문을 텍스트화하여 안경에 표시.
# 핵심 원칙:
#   1. 자바스크립트 의존 NO → 모든 콘텐츠가 HTML에 미리 박혀 있어야 함
#   2. 단순한 의미적 HTML (h1/h2/p) 사용 → 본문 추출이 정확함
#   3. 6개 섹션을 별도 HTML 파일로 → 안경에 각각 따로 등록 가능

def html_escape(s):
    """HTML 특수문자 escape."""
    if s is None:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def text_to_paragraphs_html(text):
    """줄바꿈이 들어있는 텍스트를 <p> 태그로 감싼 HTML로 변환.
    빈 줄 단위로 단락을 나누고, 단락 내부의 줄바꿈은 <br>로 보존.
    """
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


def write_section_page(filename, title, body_html, date_str):
    """안경(Web Reader)용 개별 섹션 HTML 파일 작성.

    Web Reader 친화적 구조:
    - <article> 안에 본문이 모두 들어 있음
    - 자바스크립트 없음
    - 단순한 의미적 태그만 사용
    """
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html_escape(title)} ({html_escape(date_str)})</title>
<meta name="description" content="{html_escape(title)} - {html_escape(date_str)}">
<style>
body {{ font-family: sans-serif; max-width: 700px; margin: 20px auto; padding: 0 20px; line-height: 1.7; color: #222; }}
h1 {{ font-size: 1.6em; border-bottom: 2px solid #333; padding-bottom: 0.3em; }}
h2 {{ font-size: 1.2em; margin-top: 1.5em; color: #333; }}
.meta {{ color: #888; font-size: 0.9em; margin-bottom: 1.5em; }}
p {{ margin: 0.8em 0; }}
</style>
</head>
<body>
<article>
<h1>{html_escape(title)}</h1>
<p class="meta">{html_escape(date_str)}</p>
{body_html}
</article>
</body>
</html>
"""
    os.makedirs("glasses", exist_ok=True)
    with open(f"glasses/{filename}", "w", encoding="utf-8") as f:
        f.write(html)


def build_glasses_pages(report):
    """report 딕셔너리로부터 안경(Web Reader)용 HTML 6개를 만든다.

    각 파일은 안경에 따로 등록할 수 있는 독립 페이지.
    """
    date_str = report["date"]

    # ── 1. 오늘의 날씨 ──
    w = report.get("weather", {})
    if isinstance(w, str):
        weather_body = f"<p>{html_escape(w)}</p>"
    else:
        parts = []
        for key, label in [("morning", "아침"), ("afternoon", "낮"), ("evening", "저녁")]:
            val = (w or {}).get(key) or "정보 없음"
            parts.append(f"<h2>{html_escape(label)}</h2>")
            parts.append(f"<p>{html_escape(val)}</p>")
        weather_body = "\n".join(parts)
    write_section_page("01-weather.html", "오늘의 날씨", weather_body, date_str)

    # ── 2. 성무일도 (아침/저녁/끝 3종) ──
    # 하위 호환: liturgy_morning 없으면 기존 liturgy 사용
    lit_morning = report.get("liturgy_morning") or report.get("liturgy", "")
    lit_evening = report.get("liturgy_evening", "")
    lit_night   = report.get("liturgy_night", "")

    write_section_page("02-liturgy.html", "오늘의 성무일도 (아침기도)",
                       text_to_paragraphs_html(lit_morning), date_str)
    write_section_page("02-liturgy-evening.html", "오늘의 성무일도 (저녁기도)",
                       text_to_paragraphs_html(lit_evening), date_str)
    write_section_page("02-liturgy-night.html", "오늘의 성무일도 (끝기도)",
                       text_to_paragraphs_html(lit_night), date_str)

    # ── 3. 오늘의 복음 ──
    def gospel_to_html(g):
        if not g:
            return "<p>정보 없음</p>"
        parts = []
        if g.get("reading1"):
            parts.append("<h2>제1독서</h2>")
            parts.append(text_to_paragraphs_html(g["reading1"]))
        if g.get("reading2"):
            parts.append("<h2>제2독서</h2>")
            parts.append(text_to_paragraphs_html(g["reading2"]))
        if g.get("gospel"):
            parts.append("<h2>복음</h2>")
            parts.append(text_to_paragraphs_html(g["gospel"]))
        return "\n".join(parts) if parts else "<p>정보 없음</p>"

    write_section_page("03-gospel.html", "오늘의 복음",
                       gospel_to_html(report.get("gospel")), date_str)

    # ── 4. 내일의 복음 ──
    write_section_page("04-gospel-tomorrow.html", "내일의 복음",
                       gospel_to_html(report.get("gospel_tomorrow")), date_str)

    # ── 5. 일정 ──
    cal = report.get("calendar", {}) or {}
    cal_parts = []
    for key, label in [("yesterday", "어제"), ("today", "오늘"), ("tomorrow", "내일")]:
        events = [e for e in (cal.get(key) or []) if e and e.strip() != "일정 없음"]
        cal_parts.append(f"<h2>{html_escape(label)}</h2>")
        if events:
            for e in events:
                cal_parts.append(f"<p>{html_escape(e)}</p>")
        else:
            cal_parts.append("<p>일정 없음</p>")
    write_section_page("05-calendar.html", "일정",
                       "\n".join(cal_parts), date_str)

    # ── 6. 주요 신문 기사 ──
    news = report.get("news", {}) or {}
    paper_names = {
        "hankyoreh": "한겨레",
        "chosun":    "조선일보",
        "donga":     "동아일보",
    }
    news_parts = []
    seen = set()
    for key in ["hankyoreh", "chosun", "donga"]:
        if key not in news:
            continue
        display = paper_names.get(key, key)
        if display in seen:
            continue
        seen.add(display)
        articles_list = news.get(key) or []
        news_parts.append(f"<h2>{html_escape(display)}</h2>")
        if articles_list:
            for i, t in enumerate(articles_list, 1):
                news_parts.append(f"<p>{i}. {html_escape(t)}</p>")
        else:
            news_parts.append("<p>정보 없음</p>")
    write_section_page("06-news.html", "주요 신문 기사",
                       "\n".join(news_parts), date_str)

    # ── 안내용 인덱스 (사용자가 어떤 URL이 있는지 확인용) ──
    index_html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>모닝 리포트 - 안경용 페이지 목록</title>
<style>
body {{ font-family: sans-serif; max-width: 700px; margin: 20px auto; padding: 0 20px; line-height: 1.7; }}
li {{ margin: 0.5em 0; }}
code {{ background: #f0f0f0; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }}
</style>
</head>
<body>
<h1>모닝 리포트 - 안경용 페이지 목록</h1>
<p>{html_escape(date_str)}</p>
<p>아래 URL을 안경의 Web Reader 앱에 각각 따로 등록하세요.</p>
<ol>
<li><a href="01-weather.html">오늘의 날씨</a></li>
<li><a href="02-liturgy.html">오늘의 성무일도 (아침기도)</a></li>
<li><a href="02-liturgy-evening.html">오늘의 성무일도 (저녁기도)</a></li>
<li><a href="02-liturgy-night.html">오늘의 성무일도 (끝기도)</a></li>
<li><a href="03-gospel.html">오늘의 복음</a></li>
<li><a href="04-gospel-tomorrow.html">내일의 복음</a></li>
<li><a href="06-news.html">주요 신문 기사</a></li>
</ol>
</body>
</html>
"""
    os.makedirs("glasses", exist_ok=True)
    with open("glasses/index.html", "w", encoding="utf-8") as f:
        f.write(index_html)

    print("glasses/ 폴더에 안경(Web Reader)용 HTML 6개 + 안내 페이지 1개 생성 완료!")


# ── 메인 ───────────────────────────────────────────────
def main():
    print("리포트 생성 시작...")

    # 성무일도 3종 (아침/저녁/끝) — 한 번씩만 가져오기
    liturgy_morning = get_liturgy("morning")
    liturgy_evening = get_liturgy("evening")
    liturgy_night   = get_liturgy("night")

    report = {
        "date":            today.strftime("%Y-%m-%d"),
        "generated_at":    now.strftime("%Y-%m-%d %H:%M"),
        "weather":         get_weather(),
        "liturgy":         liturgy_morning,   # 하위 호환용 (기존 아침기도)
        "liturgy_morning": liturgy_morning,
        "liturgy_evening": liturgy_evening,
        "liturgy_night":   liturgy_night,
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
            "donga":     get_news("donga"),
        }
    }

    with open("report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("report.json 생성 완료!")

    # 안경(Web Reader)용 HTML 생성
    # 오류가 나도 그냥 넘어가지 말고, 오류 내용을 파일로 남겨서 다음에 진단 가능하게.
    try:
        build_glasses_pages(report)
        # 성공했으면 기존 오류 로그 파일 제거
        if os.path.exists("glasses/_error.log"):
            try:
                os.remove("glasses/_error.log")
            except Exception:
                pass
    except Exception as e:
        import traceback
        err_msg = (
            f"안경용 HTML 생성 오류 발생\n"
            f"시각: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"오류: {e}\n\n"
            f"상세:\n{traceback.format_exc()}\n"
        )
        # 1) GitHub Actions 로그에 눈에 띄게 출력
        print("=" * 60)
        print("!!! 안경용 HTML 생성 실패 !!!")
        print(err_msg)
        print("=" * 60)
        # 2) glasses/_error.log 파일로 남겨서 나중에 확인 가능
        # (Python이 정상 종료해야 daily.yml의 git push가 이어서 실행되고,
        #  이 로그 파일이 GitHub에 올라가 사용자가 확인할 수 있다)
        try:
            os.makedirs("glasses", exist_ok=True)
            with open("glasses/_error.log", "w", encoding="utf-8") as f:
                f.write(err_msg)
        except Exception:
            pass


if __name__ == "__main__":
    main()
