#!/usr/bin/env python3
"""Bouwt de VAC-website (NL + EN) uit de wedstrijdentabel.

Bron: de gepubliceerde CSV van het Google Sheet (omgevingsvariabele SHEET_CSV_URL),
of anders het lokale bestand data/wedstrijden.csv.
Uitvoer: map dist/ met statische HTML, agenda-bestanden (.ics), sitemap en robots.txt.
"""
import csv, io, os, re, shutil, json, datetime as dt, urllib.request, html
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
DOMAIN = "https://vacdenhaag.nl"
EMAIL = "info@vacdenhaag.nl"
TZ = ZoneInfo("Europe/Amsterdam")
NOW = dt.datetime.now(TZ)
TODAY = NOW.date()
SEASON = "2026/2027"
ADDRESS = {"street": "Van Hogenhoucklaan 37", "zip": "2596 TA", "city_nl": "Den Haag", "city_en": "The Hague"}
VENUE = "Sportpark De Diepput"
CLUB = "Koninklijke HC&VV"
MATCH_MIN = 30

# ---------------------------------------------------------------- data
def read_rows():
    url = os.environ.get("SHEET_CSV_URL", "").strip()
    if url:
        with urllib.request.urlopen(url, timeout=30) as r:
            text = r.read().decode("utf-8-sig")
    else:
        with open(os.path.join(ROOT, "data", "wedstrijden.csv"), encoding="utf-8-sig") as f:
            text = f.read()
    return list(csv.DictReader(io.StringIO(text)))

def norm_key(k):
    return re.sub(r"\s+", " ", (k or "").strip().lower())

def parse_date(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None

def parse_time(s):
    m = re.match(r"^\s*(\d{1,2})[:.](\d{2})", s or "")
    return dt.time(int(m.group(1)), int(m.group(2))) if m else None

def parse_goals(s):
    s = (s or "").strip()
    return int(s) if re.fullmatch(r"\d{1,2}", s) else None

def clean_team(s):
    return re.sub(r"\s+", " ", (s or "").replace("\u2019", "'").strip())

def slug(s):
    s = s.lower().replace("&", "en").replace("'", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")

def load_matches():
    out, problems = [], []
    for i, raw in enumerate(read_rows(), start=2):
        r = {norm_key(k): v for k, v in raw.items()}
        t1, t2 = clean_team(r.get("team 1")), clean_team(r.get("team 2"))
        if not t1 or not t2 or t1.upper() == "X" or t2.upper() == "X":
            continue
        d, t = parse_date(r.get("datum")), parse_time(r.get("aftrap"))
        if not d or not t:
            problems.append(f"rij {i}: datum of aftrap onleesbaar")
            continue
        g1, g2 = parse_goals(r.get("doelpunten team 1")), parse_goals(r.get("doelpunten team 2"))
        if (g1 is None) != (g2 is None):
            problems.append(f"rij {i}: maar één score ingevuld, wedstrijd telt nog niet mee")
            g1 = g2 = None
        part = (r.get("deel") or "Deel 1").strip() or "Deel 1"
        out.append({"part": part, "round": (r.get("ronde") or "").strip(), "date": d, "time": t,
                    "field": (r.get("veld") or "").strip(), "t1": t1, "t2": t2, "g1": g1, "g2": g2})
    out.sort(key=lambda m: (m["date"], m["time"], m["field"]))
    return out, problems

def standings(matches, teams):
    st = {t: {"team": t, "p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0} for t in teams}
    played = [m for m in matches if m["g1"] is not None]
    for m in played:
        a, b = st[m["t1"]], st[m["t2"]]
        for x, gf, ga in ((a, m["g1"], m["g2"]), (b, m["g2"], m["g1"])):
            x["p"] += 1; x["gf"] += gf; x["ga"] += ga
            if gf > ga: x["w"] += 1; x["pts"] += 3
            elif gf == ga: x["d"] += 1; x["pts"] += 1
            else: x["l"] += 1
    for x in st.values():
        x["gd"] = x["gf"] - x["ga"]
    # onderling resultaat tussen teams met gelijke punten én gelijk doelsaldo
    groups = {}
    for x in st.values():
        groups.setdefault((x["pts"], x["gd"]), []).append(x["team"])
    for grp in groups.values():
        gs = set(grp)
        for t in grp:
            hp = hd = 0
            for m in played:
                if {m["t1"], m["t2"]} <= gs and t in (m["t1"], m["t2"]):
                    mine, theirs = (m["g1"], m["g2"]) if m["t1"] == t else (m["g2"], m["g1"])
                    hp += 3 if mine > theirs else 1 if mine == theirs else 0
                    hd += mine - theirs
            st[t]["hp"], st[t]["hd"] = hp, hd
    order = sorted(st.values(), key=lambda x: (-x["pts"], -x["gd"], -x["hp"], -x["hd"], -x["gf"], x["team"].lower()))
    for i, x in enumerate(order, 1):
        x["pos"] = i
    return order

# ---------------------------------------------------------------- text
T = {
 "nl": {
  "lang": "nl", "other": "en", "other_label": "EN", "other_name": "English",
  "pages": {"home": "index.html", "comp": "competitie.html", "rules": "spelregels.html", "club": "koninklijke-hvv.html", "join": "meedoen.html"},
  "nav": {"home": "Home", "comp": "Competitie", "rules": "Spelregels", "club": "Koninklijke HVV", "join": "Meedoen"},
  "brand_sub": "Vrijdag Avond Competitie", "city": ADDRESS["city_nl"],
  "days": ["maandag","dinsdag","woensdag","donderdag","vrijdag","zaterdag","zondag"],
  "months": ["januari","februari","maart","april","mei","juni","juli","augustus","september","oktober","november","december"],
  "round": "Speelronde", "field": "veld", "bye": "Vrij", "vs": "–",
  "th": ["#", "Team", "G", "W", "GL", "V", "Voor", "Tegen", "Saldo", "Ptn"],
  "th_title": ["Positie","Team","Gespeeld","Gewonnen","Gelijk","Verloren","Doelpunten voor","Doelpunten tegen","Doelsaldo","Punten"],
  "updated": "Bijgewerkt op",
 },
 "en": {
  "lang": "en", "other": "nl", "other_label": "NL", "other_name": "Nederlands",
  "pages": {"home": "index.html", "comp": "league.html", "rules": "rules.html", "club": "koninklijke-hvv.html", "join": "join.html"},
  "nav": {"home": "Home", "comp": "League", "rules": "Rules", "club": "Koninklijke HVV", "join": "Join"},
  "brand_sub": "Friday Evening League", "city": ADDRESS["city_en"],
  "days": ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"],
  "months": ["January","February","March","April","May","June","July","August","September","October","November","December"],
  "round": "Round", "field": "pitch", "bye": "Bye", "vs": "–",
  "th": ["#", "Team", "P", "W", "D", "L", "GF", "GA", "GD", "Pts"],
  "th_title": ["Position","Team","Played","Won","Drawn","Lost","Goals for","Goals against","Goal difference","Points"],
  "updated": "Updated",
 },
}

def esc(s): return html.escape(str(s), quote=True)

def fdate(d, L, weekday=True):
    s = f"{d.day} {L['months'][d.month-1]}"
    return (f"{L['days'][d.weekday()]} {s}" if weekday else s)

def ftime(t, L):
    if L["lang"] == "nl":
        return f"{t.hour:02d}.{t.minute:02d}"
    h12 = t.hour - 12 if t.hour > 12 else t.hour
    return f"{h12}.{t.minute:02d} {'pm' if t.hour >= 12 else 'am'}"

def prefix(lang):  # path prefix from page to site root
    return "" if lang == "nl" else "../"

def url_of(lang, key):
    p = T[lang]["pages"][key]
    base = DOMAIN + ("/" if lang == "nl" else "/en/")
    return base + ("" if p == "index.html" else p)

# ---------------------------------------------------------------- components
CREST = ('<svg viewBox="0 0 40 46" aria-hidden="true"><path d="M20 1 38 8v15c0 11-8 18-18 22C10 41 2 34 2 23V8Z" fill="#1d3557" stroke="#c9a24e" stroke-width="1.5"/>'
         '<text x="20" y="27" text-anchor="middle" font-family="VAC Display,Arial Narrow,sans-serif" font-weight="700" font-size="12.5" fill="#f5f0e6">VAC</text></svg>')

def head(L, key, title, desc, extra_ld=None):
    lang, other = L["lang"], T[L["other"]]
    pre = prefix(lang)
    ld = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in (extra_ld or []))
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{url_of(lang, key)}">
<link rel="alternate" hreflang="nl" href="{url_of('nl', key)}">
<link rel="alternate" hreflang="en" href="{url_of('en', key)}">
<link rel="alternate" hreflang="x-default" href="{url_of('nl', key)}">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{url_of(lang, key)}">
<meta property="og:locale" content="{'nl_NL' if lang=='nl' else 'en_GB'}">
<meta name="theme-color" content="#13243d">
<link rel="icon" href="{pre}assets/icon.svg" type="image/svg+xml">
<link rel="preload" href="{pre}assets/fonts/heroscn-bold.woff" as="font" type="font/woff" crossorigin>
<link rel="stylesheet" href="{pre}assets/site.css">
{ld}
</head>
<body>
<header class="site-head"><div class="wrap">
<a class="brand" href="{L['pages']['home']}">{CREST}<b>VAC</b><span>{esc(L['brand_sub'])}</span></a>
<nav class="nav" aria-label="{'Hoofdmenu' if lang=='nl' else 'Main menu'}">
{''.join(f'<a href="{L["pages"][k]}"{" aria-current=\"page\"" if k==key else ""}>{esc(L["nav"][k])}</a>' for k in ("home","comp","rules","club","join"))}
</nav>
<a class="lang" href="{('en/' if lang=='nl' else '../') + other['pages'][key]}" hreflang="{other['lang']}" lang="{other['lang']}" title="{'English' if lang=='nl' else 'Nederlands'}">{L['other_label']}</a>
</div></header>
<main><div class="wrap">
"""

def foot(L):
    nl = L["lang"] == "nl"
    return f"""</div></main>
<footer class="site-foot"><div class="wrap">
<div><b>VAC</b> · {esc(L['brand_sub'])}<br>{'7 tegen 7, op vrijdagavond bij HVV.' if nl else '7-a-side football, Friday evenings at HVV.'}</div>
<div>{VENUE}<br>{ADDRESS['street']}<br>{ADDRESS['zip']} {L['city']}<br><span class="mail-small">{EMAIL}</span></div>
<div>{L['updated']} {fdate(NOW.date(), L, False)} {NOW.year}, {NOW:%H.%M}<br>{'Deze website plaatst geen cookies en gebruikt geen trackers.' if nl else 'This website sets no cookies and uses no trackers.'}</div>
</div></footer>
<script src="{prefix(L['lang'])}assets/site.js" defer></script>
</body>
</html>
"""

def score_html(m):
    if m["g1"] is None:
        return '<span class="score vs"><b>·</b><b>·</b></span>'
    return f'<span class="score" aria-label="{m["g1"]}-{m["g2"]}"><b>{m["g1"]}</b><b>{m["g2"]}</b></span>'

def match_row(m, L, result=False):
    when = "" if result else f'<span class="when num">{ftime(m["time"], L)}<small>{L["field"]} {esc(m["field"])}</small></span>'
    return (f'<div class="match{" res" if result else ""}" data-teams="{esc(slug(m["t1"]))} {esc(slug(m["t2"]))}">'
            f'{when}<span class="t1">{esc(m["t1"])}</span>{score_html(m)}<span class="t2">{esc(m["t2"])}</span></div>')

def round_board(rnd, ms, teams, L, extra_cls="", result=False, all_ms=None):
    d = ms[0]["date"]
    src = all_ms or ms
    playing = {m["t1"] for m in src} | {m["t2"] for m in src}
    byes = [t for t in teams if t not in playing]
    bye = f'<div class="bye"><b>{L["bye"]}</b>{esc(", ".join(byes))}</div>' if (byes and not result) else ""
    rows = "".join(match_row(m, L, result) for m in ms)
    return (f'<div class="board round{extra_cls}" data-round="{esc(rnd)}"><div class="board-head"><h3>{L["round"]} {esc(rnd)}</h3>'
            f'<span>{fdate(d, L)}</span></div>{rows}{bye}</div>')

def stand_table(order, L, limit=None, caption=""):
    th = "".join(f'<th scope="col" title="{esc(t)}"{" class=\"team\"" if i==1 else (" class=\"pos\"" if i==0 else "")}>{esc(h)}</th>'
                 for i, (h, t) in enumerate(zip(L["th"], L["th_title"])))
    rows = ""
    for x in order[:limit] if limit else order:
        gd = f'+{x["gd"]}' if x["gd"] > 0 else str(x["gd"]).replace("-", "−")
        rows += (f'<tr data-team="{esc(slug(x["team"]))}"><td class="pos">{x["pos"]}</td><td class="team">{esc(x["team"])}</td><td>{x["p"]}</td>'
                 f'<td>{x["w"]}</td><td>{x["d"]}</td><td>{x["l"]}</td><td>{x["gf"]}</td><td>{x["ga"]}</td><td>{gd}</td><td class="pts">{x["pts"]}</td></tr>')
    cap = f'<caption class="sr-only" style="position:absolute;left:-9999px">{esc(caption)}</caption>' if caption else ""
    return f'<div class="table-wrap"><table class="stand">{cap}<thead><tr>{th}</tr></thead><tbody>{rows}</tbody></table></div>'

def by_round(matches):
    rounds = {}
    for m in matches:
        rounds.setdefault((m["part"], m["round"]), []).append(m)
    return rounds

# ---------------------------------------------------------------- structured data
def org_ld(L):
    nl = L["lang"] == "nl"
    return {
        "@context": "https://schema.org", "@type": "SportsOrganization",
        "name": "VAC – Vrijdag Avond Competitie", "alternateName": ["VAC Den Haag", "Friday Evening League The Hague"],
        "url": DOMAIN + "/", "email": EMAIL, "sport": "Soccer",
        "description": ("7-tegen-7-voetbalcompetitie voor 35-plussers op vrijdagavond bij HVV in Den Haag." if nl
                        else "7-a-side football league for players aged 35+ on Friday evenings at HVV in The Hague."),
        "location": place_ld(L),
    }

def place_ld(L):
    return {"@type": "Place", "name": f"{VENUE} ({CLUB})",
            "address": {"@type": "PostalAddress", "streetAddress": ADDRESS["street"], "postalCode": ADDRESS["zip"],
                        "addressLocality": L["city"], "addressCountry": "NL"}}

def events_ld(ms, L):
    out = []
    for m in ms:
        start = dt.datetime.combine(m["date"], m["time"], TZ)
        out.append({"@context": "https://schema.org", "@type": "SportsEvent",
                    "name": f"VAC: {m['t1']} – {m['t2']}", "sport": "Soccer",
                    "startDate": start.isoformat(), "endDate": (start + dt.timedelta(minutes=MATCH_MIN)).isoformat(),
                    "eventStatus": "https://schema.org/EventScheduled",
                    "location": place_ld(L),
                    "homeTeam": {"@type": "SportsTeam", "name": m["t1"]}, "awayTeam": {"@type": "SportsTeam", "name": m["t2"]},
                    "organizer": {"@type": "SportsOrganization", "name": "VAC – Vrijdag Avond Competitie", "url": DOMAIN + "/"}})
    return out

# ---------------------------------------------------------------- pages
def page_home(L, matches, teams, order):
    nl = L["lang"] == "nl"
    rounds = by_round([m for m in matches if m["part"] == "Deel 1"])
    upcoming = [(k, v) for k, v in rounds.items() if v[0]["date"] >= TODAY and any(m["g1"] is None for m in v)]
    done = [(k, v) for k, v in rounds.items() if any(m["g1"] is not None for m in v)]
    nxt = upcoming[0] if upcoming else None
    last = done[-1] if done else None
    title = ("VAC Den Haag · 7 tegen 7 voetbal op vrijdagavond (35+)" if nl
             else "VAC The Hague · 7-a-side football on Friday evenings (35+)")
    desc = ("De Vrijdag Avond Competitie (VAC): 7-tegen-7-voetbal voor 35-plussers bij HVV in Den Haag. Programma, uitslagen, stand en meedoen."
            if nl else "The Vrijdag Avond Competitie (VAC): 7-a-side football for over-35s at HVV in The Hague. Fixtures, results, table and how to join.")
    ld = [org_ld(L)] + (events_ld(nxt[1], L) if nxt else [])
    P = L["pages"]
    h = head(L, "home", title, desc, ld)
    h += f"""<section class="hero">
<p class="kicker">{'Seizoen' if nl else 'Season'} {SEASON}</p>
<h1>{'Vrijdag Avond Competitie' if nl else 'Friday Evening League'}<br><em>{'bij HVV' if nl else 'at HVV'}</em></h1>
<div class="meta"><span>{'7 tegen 7' if nl else '7-a-side'}</span><span>35+</span><span>{'Vrijdag 20:30u en 21:15u' if nl else 'Fridays 8.30 and 9.15 pm'}</span><span>{'Den Haag' if nl else 'The Hague'}</span></div>
<div><a class="btn" href="{P['join']}">{'Doe jij volgend seizoen ook mee?' if nl else 'Join us next season?'} <span aria-hidden="true">→</span></a></div>
</section>
<section class="grid2">"""
    if nxt:
        h += f'<div class="stack"><div class="sec-head"><h2>{"Volgende speelronde" if nl else "Next round"}</h2><a href="{P["comp"]}#programma">{"Het hele programma" if nl else "Full schedule"}</a></div>{round_board(nxt[0][1], nxt[1], teams, L)}</div>'
    if last:
        h += f'<div class="stack"><div class="sec-head"><h2>{"Laatste uitslagen" if nl else "Latest results"}</h2><a href="{P["comp"]}#uitslagen">{"Alle uitslagen" if nl else "All results"}</a></div>{round_board(last[0][1], [m for m in last[1] if m["g1"] is not None], teams, L, result=True)}</div>'
    h += "</section>"
    h += f"""<section><div class="sec-head"><h2>{'Stand' if nl else 'Table'}</h2></div>
{stand_table(order, L, caption='Stand' if nl else 'Table')}</section>
<section class="cta"><h2>{'Doe jij volgend seizoen ook mee?' if nl else 'Join us next season?'}</h2>
<p>{'Een team van collega’s, vaders van het schoolplein, oud-teamgenoten of vrienden uit de buurt? We horen graag van teams die op vrijdagavond willen voetballen.' if nl else 'A team of colleagues, school-gate dads, former teammates or friends from the neighbourhood? We would love to hear from teams who want to play on Friday evenings.'}</p>
<a class="btn" href="{P['join']}">{'Zo doe je mee' if nl else 'How to join'} <span aria-hidden="true">→</span></a></section>
"""
    return h + foot(L)

def page_comp(L, matches, teams, order):
    nl = L["lang"] == "nl"
    title = ("Programma, uitslagen en stand · VAC Den Haag" if nl else "Fixtures, results and table · VAC The Hague")
    desc = ("Het volledige programma, alle uitslagen en de actuele stand van de Vrijdag Avond Competitie bij HVV. Met een agenda-abonnement per team."
            if nl else "Full fixtures, all results and the current table of the VAC Friday Evening League at HVV. With a calendar feed per team.")
    upcoming = [m for m in matches if m["date"] >= TODAY and m["g1"] is None][:8]
    h = head(L, "comp", title, desc, [org_ld(L)] + events_ld(upcoming, L))
    opts = "".join(f'<option value="{esc(slug(t))}">{esc(t)}</option>' for t in teams)
    h += f"""<section class="hero" style="padding-bottom:0">
<p class="kicker">{'Seizoen' if nl else 'Season'} {SEASON} · {'deel 1' if nl else 'part 1'}</p>
<h1>{'Competitie' if nl else 'League'}</h1>
<p class="lead">{'Stand, programma en uitslagen van deel 1. Na de winterstop speelt de bovenste helft de Champions League en de onderste helft de Europa League.' if nl else 'Table, fixtures and results of part 1. After the winter break, the top half plays the Champions League and the bottom half the Europa League.'}</p>
</section>
<section id="stand"><div class="sec-head"><h2>{'Stand' if nl else 'Table'}</h2></div>
{stand_table(order, L, caption='Stand deel 1' if nl else 'Table part 1')}
<p class="note">{'Winst 3, gelijk 1, verlies 0 punten. Bij gelijke punten telt eerst het doelsaldo, dan het onderlinge resultaat, dan het aantal gescoorde doelpunten.' if nl else 'Win 3, draw 1, loss 0 points. Teams level on points are separated by goal difference, then head-to-head result, then goals scored.'}</p>
</section>
<div class="filter" id="programma"><label for="teamfilter">{'Kies een team' if nl else 'Choose a team'}</label>
<select id="teamfilter"><option value="">{'Alle teams' if nl else 'All teams'}</option>{opts}</select></div>
<section><div class="sec-head"><h2>{'Programma' if nl else 'Fixtures'}</h2></div><div class="rounds">"""
    d1 = [m for m in matches if m["part"] == "Deel 1"]
    full = by_round(d1)
    todo = by_round([m for m in d1 if m["g1"] is None])
    done = by_round([m for m in d1 if m["g1"] is not None])
    for k, ms in todo.items():
        h += round_board(k[1], ms, teams, L, all_ms=full[k])
    if not todo:
        h += f'<p>{"Alle wedstrijden van deel 1 zijn gespeeld." if nl else "All matches of part 1 have been played."}</p>'
    h += f"""</div></section>
<section id="uitslagen"><div class="sec-head"><h2>{'Uitslagen' if nl else 'Results'}</h2></div><div class="rounds">"""
    for k, ms in reversed(list(done.items())):
        h += round_board(k[1], ms, teams, L, result=True)
    h += "</div></section>"
    # agenda
    feed_intro = ("Zet het programma van je team in je eigen agenda. Wijzigingen en uitslagen komen er vanzelf in. Kies je team en tik op Abonneren."
                  if nl else "Put your team’s fixtures in your own calendar. Changes and results update automatically. Pick your team and tap Subscribe.")
    h += f"""<section id="agenda"><div class="sec-head"><h2>{'Agenda per team' if nl else 'Calendar per team'}</h2></div>
<p class="prose">{feed_intro}</p>
<ul class="cal-list">"""
    for t in teams:
        s = slug(t)
        h += (f'<li><span>{esc(t)}</span><span><a href="webcal://vacdenhaag.nl/agenda/{s}.ics">{"Abonneren" if nl else "Subscribe"}</a> · '
              f'<a href="{prefix(L["lang"])}agenda/{s}.ics">.ics</a></span></li>')
    h += f"""</ul>
<details class="faq" style="margin-top:1rem"><summary>{'Werkt Abonneren niet?' if nl else 'Subscribe not working?'}</summary>
<p>{'Kopieer het adres van je team, bijvoorbeeld' if nl else 'Copy your team’s address, for example'} <code>https://vacdenhaag.nl/agenda/{slug(teams[0])}.ics</code>.
{'In Google Agenda: Andere agenda’s, Via URL, en plak het adres. In Outlook: Agenda toevoegen, Abonneren vanaf internet. Op de iPhone werkt de knop Abonneren direct.' if nl else 'In Google Calendar: Other calendars, From URL, and paste the address. In Outlook: Add calendar, Subscribe from web. On iPhone the Subscribe button works directly.'}</p></details>
</section>"""
    return h + foot(L)

RULES = {
 "nl": [("Spelers", "6 veldspelers en 1 keeper."), ("Leeftijd", "35+."), ("Veld", "Half veld."), ("Doelen", "Pupillendoelen (5 × 2 meter)."),
        ("Speeltijd", "30 minuten per wedstrijd. Per speelronde speelt elk team 2 wedstrijden."), ("Wissels", "Doorlopend wisselen, zo vaak als je wilt."),
        ("Zijlijn", "Geen ingooi. De bal wordt ingepast of ingeschoten."), ("Buitenspel", "Geen buitenspel."),
        ("Sliding", "Niet toegestaan. Overig grof spel uiteraard ook niet."), ("Spelleiding", "Teams regelen zelf de spelbegeleiding. Er wordt alleen centraal gefloten voor het begin en het einde van de wedstrijden."),
        ("Fair play", "Onsportief gedrag? Dan wordt de speler gewisseld. Aanvoerders zijn hier verantwoordelijk voor."),
        ("Ranglijst", "Winst 3, gelijk 1, verlies 0 punten. Bij gelijke stand geldt eerst doelsaldo en daarna onderling resultaat.")],
 "en": [("Players", "6 outfield players and 1 goalkeeper."), ("Age", "35+."), ("Pitch", "Half pitch."), ("Goals", "Youth goals (5 × 2 metres)."),
        ("Match length", "30 minutes per match. Each team plays 2 matches per round."), ("Substitutes", "Rolling substitutions, as often as you like."),
        ("Touchline", "No throw-ins. The ball is passed or kicked back in."), ("Offside", "No offside."),
        ("Sliding tackles", "Not allowed. Nor is any other foul play, of course."), ("Refereeing", "Teams referee their own matches. A central whistle only marks the start and end of the matches."),
        ("Fair play", "Unsporting behaviour? Then the player is substituted. Captains are responsible for this."),
        ("League table", "Win 3, draw 1, loss 0 points. Level on points: goal difference first, then head-to-head result.")],
}

def page_rules(L):
    nl = L["lang"] == "nl"
    title = ("Spelregels en praktische info · VAC Den Haag" if nl else "Rules and practical info · VAC The Hague")
    desc = ("De spelregels van de VAC: 7 tegen 7, 35+, half veld, geen buitenspel, geen slidings. Plus speeltijden en locatie bij HVV in Den Haag."
            if nl else "The rules of the VAC: 7-a-side, 35+, half pitch, no offside, no sliding tackles. Plus kick-off times and location at HVV in The Hague.")
    pre = prefix(L["lang"])
    h = head(L, "rules", title, desc, [org_ld(L)])
    rules = "".join(f'<div class="rule"><dt>{esc(a)}</dt><dd>{esc(b)}</dd></div>' for a, b in RULES[L["lang"]])
    h += f"""<section class="hero" style="padding-bottom:0"><p class="kicker">{'Seizoen' if nl else 'Season'} {SEASON}</p>
<h1>{'Spelregels' if nl else 'Rules'}</h1>
<p class="lead">{'Kort en duidelijk: zo spelen we.' if nl else 'Short and simple: this is how we play.'}</p>
<div class="downloads"><a class="btn" href="{pre}downloads/VAC-spelregels-2026-2027.pdf">{'Spelregels (PDF)' if nl else 'Rules in Dutch (PDF)'}</a>
<a class="btn ghost" href="{pre}downloads/VAC-rules-2026-2027-EN.pdf">{'Rules in English (PDF)' if nl else 'Rules (PDF)'}</a></div></section>
<section><dl class="rules">{rules}</dl></section>
<section><div class="sec-head"><h2>{'Praktisch' if nl else 'Practical'}</h2></div>
<dl class="rules">
<div class="rule"><dt>{'Waar' if nl else 'Where'}</dt><dd>{VENUE}, {CLUB}<br>{ADDRESS['street']}, {ADDRESS['zip']} {L['city']}<br><a href="{L['pages']['club']}">{'Over de club en de route' if nl else 'About the club and directions'}</a></dd></div>
<div class="rule"><dt>{'Wanneer' if nl else 'When'}</dt><dd>{'Vrijdagavond. Eerste wedstrijd om 20.30, tweede om 21.15 uur.' if nl else 'Friday evening. First match at 8.30 pm, second at 9.15 pm.'}</dd></div>
<div class="rule"><dt>{'Seizoen' if nl else 'Season'}</dt><dd>{'Deel 1 van september tot en met december. Eén poule; elk team een keer tegen elkaar. Deel 2 van februari tot en met mei. Teams verdeeld in CL en EL. Elk team speelt twee keer tegen elkaar. Iedereen begint weer op 0.' if nl else 'Part 1 runs from September to December. One league; each team plays every other team once. Part 2 runs from February to May. Teams are split into the CL and EL. Each team plays the others twice. Everyone starts again on 0.'}</dd></div>
<div class="rule"><dt>{'Derde helft' if nl else 'Third half'}</dt><dd>{'Na de laatste wedstrijd drinken we samen nog wat.' if nl else 'After the last match, we have a drink together.'}</dd></div>
</dl></section>"""
    return h + foot(L)

def page_club(L):
    nl = L["lang"] == "nl"
    title = ("Koninklijke HVV · Sportpark De Diepput · VAC Den Haag" if nl else "Koninklijke HVV · Sportpark De Diepput · VAC The Hague")
    desc = ("De VAC speelt bij de Koninklijke Haagsche Cricket & Voetbal Vereeniging (HVV) op Sportpark De Diepput in Den Haag. Historie, adres en route."
            if nl else "The VAC plays at the Koninklijke Haagsche Cricket & Voetbal Vereeniging (HVV) at Sportpark De Diepput in The Hague. History, address and directions.")
    addr_q = "Van+Hogenhoucklaan+37,+2596+TA+Den+Haag"
    ld = [{"@context": "https://schema.org", "@type": "SportsActivityLocation", "name": f"{VENUE} – Koninklijke Haagsche Cricket & Voetbal Vereeniging",
           "address": place_ld(L)["address"], "url": "https://www.konhcvv.nl/"}]
    h = head(L, "club", title, desc, ld)
    h += f"""<section class="hero" style="padding-bottom:0"><p class="kicker">{'De club en de locatie' if nl else 'The club and the venue'}</p>
<h1>Koninklijke <em>HVV</em></h1>
<p class="lead">{'De VAC wordt gespeeld bij de Koninklijke Haagsche Cricket & Voetbal Vereeniging, in Den Haag gewoon HVV. Een club met een lange voetbalgeschiedenis, die de VAC op vrijdagavond een thuis geeft.' if nl else 'The VAC is played at the Koninklijke Haagsche Cricket & Voetbal Vereeniging, known in The Hague simply as HVV. A club with a long football history, and the home of the VAC on Friday evenings.'}</p></section>
<section class="facts">
<div class="fact"><b class="num">1883</b><span>{'opgericht' if nl else 'founded'}</span></div>
<div class="fact"><b class="num">10×</b><span>{'landskampioen, tussen 1890 en 1914' if nl else 'Dutch champions, between 1890 and 1914'}</span></div>
<div class="fact"><b class="num">1978</b><span>{'het predicaat Koninklijk' if nl else 'granted the Royal title'}</span></div>
<div class="fact"><b class="num">1898</b><span>{'sindsdien op De Diepput' if nl else 'at De Diepput ever since'}</span></div>
</section>
<section class="grid2">
<div class="prose"><div class="sec-head"><h2>{'Historie' if nl else 'History'}</h2></div>
<p>{'HVV was voor de Eerste Wereldoorlog de succesvolste voetbalclub van Nederland, met tien landstitels tussen 1890 en 1914. In 1978 kreeg de vereniging het predicaat Koninklijk.' if nl else 'Before the First World War, HVV was the most successful football club in the Netherlands, winning ten national titles between 1890 and 1914. In 1978 the club was granted the title Koninklijke (Royal).'}</p>
<p>{'Sinds 1898 speelt de club op De Diepput, op de grens van Benoordenhout en Wassenaar. Daar staan op vrijdagavond ook de teams van de VAC op het veld.' if nl else 'Since 1898 the club has played at De Diepput, on the border of Benoordenhout and Wassenaar. That is also where the VAC teams take the field on Friday evenings.'}</p>
<p><a href="https://www.konhcvv.nl/" rel="noopener">{'Website van de Koninklijke HC&VV' if nl else 'Koninklijke HC&VV website'}</a></p></div>
<div class="panel"><div class="sec-head"><h2>{'Adres en route' if nl else 'Address and directions'}</h2></div>
<p>{VENUE}<br>{ADDRESS['street']}<br>{ADDRESS['zip']} {L['city']}</p>
<p>{'We spelen op de velden 2a, 2b, 3a en 3b: twee velden, elk in tweeën gedeeld.' if nl else 'We play on pitches 2a, 2b, 3a and 3b: two pitches, each split in half.'}</p>
<div class="downloads"><a class="btn" href="https://www.google.com/maps/dir/?api=1&amp;destination={addr_q}" rel="noopener">{'Route plannen' if nl else 'Get directions'}</a>
<a class="btn ghost" href="https://www.openstreetmap.org/search?query={addr_q}" rel="noopener">OpenStreetMap</a></div></div>
</section>"""
    return h + foot(L)

FAQ = {
 "nl": [("Voor wie is de VAC?", "Voor teams van spelers van 35 jaar en ouder die op vrijdagavond willen voetballen. De huidige teams zijn ontstaan op het werk, op het schoolplein, als spin-off van een seniorenteam of gewoon in de vriendenkring of de buurt."),
        ("Wanneer wordt er gespeeld?", "Op vrijdagavond. Deel 1 loopt van september tot en met december, deel 2 van februari tot en met mei. De wedstrijden beginnen om 20.30 en 21.15 uur."),
        ("Waar wordt er gespeeld?", "Bij HVV op Sportpark De Diepput, Van Hogenhoucklaan 37 in Den Haag."),
        ("Hoeveel speel je per avond?", "Twee wedstrijden van 30 minuten, 7 tegen 7 op een half veld."),
        ("Is er een scheidsrechter?", "Nee. Teams regelen zelf de spelbegeleiding. Er wordt alleen centraal gefloten voor het begin en het einde van de wedstrijden."),
        ("Wat kost het en hoe meld ik mijn team aan?", "Stuur een mail naar info@vacdenhaag.nl met de naam van je team en een contactpersoon. We sturen je dan alle informatie, ook over de kosten.")],
 "en": [("Who is the VAC for?", "Teams of players aged 35 and over who want to play football on Friday evenings. The current teams started at work, at the school gate, as a spin-off of a senior team, or simply among friends or neighbours."),
        ("When do we play?", "On Friday evenings. Part 1 runs from September to December, part 2 from February to May. Matches kick off at 8.30 pm and 9.15 pm."),
        ("Where do we play?", "At HVV, Sportpark De Diepput, Van Hogenhoucklaan 37 in The Hague."),
        ("How much do you play per evening?", "Two matches of 30 minutes, 7-a-side on half a pitch."),
        ("Is there a referee?", "No. Teams referee their own matches. A central whistle only marks the start and end of the matches."),
        ("What does it cost and how do I sign up my team?", "Send an email to info@vacdenhaag.nl with your team name and a contact person. We will send you all the information, including the costs.")],
}

def page_join(L):
    nl = L["lang"] == "nl"
    title = ("Meedoen met je team · 7 tegen 7 voetbal 35+ in Den Haag · VAC" if nl else "Join with your team · 7-a-side football 35+ in The Hague · VAC")
    desc = ("Wil je met je team op vrijdagavond 7 tegen 7 voetballen in Den Haag? De VAC bij HVV zoekt teams van 35-plussers voor volgend seizoen."
            if nl else "Want to play 7-a-side football with your team on Friday evenings in The Hague? The VAC at HVV welcomes teams of over-35s for next season.")
    faq_ld = {"@context": "https://schema.org", "@type": "FAQPage",
              "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in FAQ[L["lang"]]]}
    h = head(L, "join", title, desc, [org_ld(L), faq_ld])
    faq = "".join(f"<details><summary>{esc(q)}</summary><p>{esc(a)}</p></details>" for q, a in FAQ[L["lang"]])
    h += f"""<section class="hero" style="padding-bottom:0"><p class="kicker">{'Meedoen en contact' if nl else 'Join and contact'}</p>
<h1>{'Doen jullie volgend seizoen <em>ook mee?</em>' if nl else 'Is your team joining us <em>next season?</em>'}</h1>
<p class="lead">{'Op vrijdagavond spelen we twee wedstrijden van een half uur, fanatiek genoeg om te willen winnen, met fair play en oog voor het feit dat we geen 18 meer zijn. Plus; een relevant zwaartepunt op de derde helft.' if nl else 'On Friday evenings we play two half-hour matches, competitive enough to want to win, with fair play and with a nod to the fact that we are no longer 18. Plus: a fair share of the emphasis on the third half.'}</p>
<p style="margin:0"><b>{'Eerst eens proberen?' if nl else 'Want to try it first?'}</b> {'Informeer naar de mogelijkheden om een proefpot in te plannen.' if nl else 'Ask us about arranging a trial match.'}</p></section>
<section class="grid2">
<div class="prose"><div class="sec-head"><h2>{'Zo werkt het' if nl else 'How it works'}</h2></div>
<p>{'De VAC bestaat al een aantal jaren en telt in het seizoen 2026-2027 dertien teams. De teams zijn verschillend samengesteld en op allerlei manieren ontstaan: op het werk, op het schoolplein, als spin-off van een seniorenteam, of gewoon met vrienden (uit de buurt). Wat ze delen: iedereen wil nog lekker op vrijdagavond voetballen.' if nl else 'The VAC has been running for several years and has thirteen teams in the 2026-2027 season. Each team has its own mix of players, and they came together in all sorts of ways: at work, at the school gate, as a spin-off of a senior team, or simply with friends (from the neighbourhood). What they share: everyone still loves a game of football on a Friday evening.'}</p>
<p>{'We spelen 7 tegen 7 op een half veld, zonder buitenspel en zonder slidings. De teams fluiten zelf, en de aanvoerders zorgen samen voor een sportieve wedstrijd.' if nl else 'We play 7-a-side on half a pitch, without offside and without sliding tackles. The teams referee themselves, and the captains make sure the match stays sporting.'}</p>
<p><a href="{L['pages']['rules']}">{'Lees de spelregels' if nl else 'Read the rules'}</a></p></div>
<div class="panel"><div class="sec-head"><h2>{'Aanmelden' if nl else 'Sign up'}</h2></div>
<p>{'Mail de naam van je team en een contactpersoon naar:' if nl else 'Email your team name and a contact person to:'}</p>
<p class="mail">{EMAIL}</p>
<div class="downloads"><a class="btn" href="mailto:{EMAIL}?subject={'Aanmelding%20VAC' if nl else 'VAC%20sign-up'}">{'Mail ons' if nl else 'Email us'}</a>
<button class="btn ghost" type="button" data-copy="{EMAIL}">{'Kopieer adres' if nl else 'Copy address'}</button></div></div>
</section>
<section class="faq"><div class="sec-head"><h2>{'Veelgestelde vragen' if nl else 'Frequently asked questions'}</h2></div>{faq}</section>"""
    return h + foot(L)

# ---------------------------------------------------------------- calendar
def ics_escape(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

def fold(line):
    b = line.encode("utf-8")
    if len(b) <= 75:
        return line
    out, cur = [], b""
    for ch in line:
        e = ch.encode("utf-8")
        if len(cur) + len(e) > (75 if not out else 74):
            out.append(cur.decode("utf-8")); cur = b""
        cur += e
    out.append(cur.decode("utf-8"))
    return "\r\n ".join(out)

def ics(name, ms):
    stamp = NOW.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//VAC Den Haag//Programma//NL", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             f"X-WR-CALNAME:{ics_escape(name)}", "X-WR-TIMEZONE:Europe/Amsterdam",
             "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"]
    for m in ms:
        start = dt.datetime.combine(m["date"], m["time"], TZ).astimezone(dt.timezone.utc)
        end = start + dt.timedelta(minutes=MATCH_MIN)
        res = f" ({m['g1']}-{m['g2']})" if m["g1"] is not None else ""
        uid = f"{m['date']:%Y%m%d}-{m['time']:%H%M}-{slug(m['field'])}-{slug(m['t1'])}-{slug(m['t2'])}@vacdenhaag.nl"
        lines += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}", f"DTSTART:{start:%Y%m%dT%H%M%SZ}", f"DTEND:{end:%Y%m%dT%H%M%SZ}",
                  f"SUMMARY:{ics_escape('VAC: ' + m['t1'] + ' – ' + m['t2'] + res)}",
                  f"LOCATION:{ics_escape(VENUE + ', ' + ADDRESS['street'] + ', ' + ADDRESS['zip'] + ' Den Haag')}",
                  f"DESCRIPTION:{ics_escape('Speelronde ' + m['round'] + ' · veld ' + m['field'] + chr(10) + DOMAIN + '/competitie.html')}",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"

# ---------------------------------------------------------------- build
def main():
    matches, problems = load_matches()
    teams = sorted({m["t1"] for m in matches} | {m["t2"] for m in matches}, key=str.lower)
    order = standings([m for m in matches if m["part"] == "Deel 1"], teams)
    if os.path.exists(DIST):
        shutil.rmtree(DIST)
    shutil.copytree(os.path.join(ROOT, "site"), DIST)
    os.makedirs(os.path.join(DIST, "en"), exist_ok=True)
    os.makedirs(os.path.join(DIST, "agenda"), exist_ok=True)
    for lang in ("nl", "en"):
        L = T[lang]
        out = DIST if lang == "nl" else os.path.join(DIST, "en")
        pages = {"home": page_home(L, matches, teams, order), "comp": page_comp(L, matches, teams, order),
                 "rules": page_rules(L), "club": page_club(L), "join": page_join(L)}
        for k, s in pages.items():
            with open(os.path.join(out, L["pages"][k]), "w", encoding="utf-8") as f:
                f.write(s)
    for t in teams:
        ms = [m for m in matches if t in (m["t1"], m["t2"])]
        with open(os.path.join(DIST, "agenda", slug(t) + ".ics"), "w", encoding="utf-8", newline="") as f:
            f.write(ics(f"VAC – {t}", ms))
    with open(os.path.join(DIST, "agenda", "vac-alle-wedstrijden.ics"), "w", encoding="utf-8", newline="") as f:
        f.write(ics("VAC – alle wedstrijden", matches))
    # sitemap, robots, llms.txt, CNAME
    urls = [url_of(l, k) for l in ("nl", "en") for k in ("home", "comp", "rules", "club", "join")]
    sm = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    sm += "".join(f"<url><loc>{u}</loc><lastmod>{TODAY.isoformat()}</lastmod></url>\n" for u in urls) + "</urlset>\n"
    open(os.path.join(DIST, "sitemap.xml"), "w").write(sm)
    open(os.path.join(DIST, "robots.txt"), "w").write(f"User-agent: *\nAllow: /\n\nSitemap: {DOMAIN}/sitemap.xml\n")
    open(os.path.join(DIST, "CNAME"), "w").write("vacdenhaag.nl\n")
    llms = (f"# VAC – Vrijdag Avond Competitie (Den Haag)\n\n> 7-tegen-7-voetbalcompetitie voor 35-plussers op vrijdagavond bij HVV "
            f"(Koninklijke HC&VV), {VENUE}, {ADDRESS['street']}, {ADDRESS['zip']} Den Haag. Contact: {EMAIL}.\n\n"
            f"- [Programma, uitslagen en stand]({DOMAIN}/competitie.html)\n- [Spelregels]({DOMAIN}/spelregels.html)\n"
            f"- [Koninklijke HVV en route]({DOMAIN}/koninklijke-hvv.html)\n- [Meedoen met je team]({DOMAIN}/meedoen.html)\n"
            f"- [English version]({DOMAIN}/en/)\n")
    open(os.path.join(DIST, "llms.txt"), "w").write(llms)
    print(f"{len(matches)} wedstrijden, {len(teams)} teams, {sum(m['g1'] is not None for m in matches)} gespeeld")
    for p in problems:
        print("LET OP:", p)
    for x in order:
        print(f"{x['pos']:>2} {x['team']:<22} {x['p']:>2} {x['pts']:>3} {x['gf']:>3}-{x['ga']:<3} {x['gd']:+}")

if __name__ == "__main__":
    main()
