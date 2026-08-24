from __future__ import annotations

from fasthtml.common import *

from . import db

NAV = (("⌂", "Home", "/"), ("✦", "Coworkers", "/agents"), ("⌁", "Skills", "/skills"),
       ("▣", "Computers", "/admin/computers"), ("◈", "Boundaries", "/admin/boundaries"),
       ("◷", "Audit", "/admin/audit"))


def shell(active: str, *content, title: str = "FastBot"):
    sidebar = Aside(
        A(Div("F", cls="brand-mark"), Div(Strong("FastBot"), Small("AI coworker workspace")), href="/", cls="brand"),
        Nav(*[A(Span(icon), label, href=href, cls="nav-link active" if href == active else "nav-link") for icon, label, href in NAV]),
        Div(Span(cls="status-dot"), Div(Strong("Local workspace"), Small("Single-user administrator")), cls="instance"),
        cls="sidebar",
    )
    return Title(title), Div(sidebar, Main(*content, cls="main"), cls="app-shell")


def topbar(kicker: str, title: str, subtitle: str, *actions):
    return Header(Div(Small(kicker, cls="eyebrow"), H1(title), P(subtitle)), Div(*actions, cls="top-actions"), cls="topbar")


def agent_card(agent):
    return Article(
        Div(agent["icon"], cls="agent-icon"),
        Div(H3(agent["name"]), P(agent["title"], cls="muted"), P(agent["description"]), cls="agent-copy"),
        A("Open channel", href=f"/agents/{agent['id']}/launch", cls="button secondary"), cls="agent-card")


def home_page():
    agents = db.rows("SELECT * FROM agents ORDER BY id")
    channels = db.rows("SELECT c.*,a.name agent_name,a.icon FROM channels c JOIN agents a ON a.id=c.agent_id ORDER BY c.updated_at DESC LIMIT 8")
    return shell("/",
        topbar("WORKSPACE", "Good to see you", "Choose a coworker or continue where you left off.", A("New coworker", href="/agents", cls="button")),
        Section(Div(H2("Your coworkers"), P("Specialists with their own instructions, channels, and governed tools.", cls="muted"), cls="section-head"),
                Div(*[agent_card(a) for a in agents], cls="agent-grid")),
        Section(Div(H2("Recent channels"), cls="section-head"),
                Div(*([A(Span(c["icon"], cls="mini-icon"), Div(Strong(c["title"]), Small(c["agent_name"])), Span("→"), href=f"/channel/{c['id']}", cls="channel-row") for c in channels]
                      or [Div(P("No channels yet. Launch a coworker to begin."), cls="empty")]), cls="channel-list")))


def channel_page(channel, agent, messages):
    bubbles = []
    for msg in messages:
        bubbles.append(Div(Div(msg["content"], cls="bubble markdown"), cls=f"message {msg['role']}"))
    return shell("",
        Div(
            Header(A("‹", href="/", cls="icon-button"), Div(Span(agent["icon"], cls="mini-icon"), Div(Strong(channel["title"]), Small(agent["title"]))),
                   Div(Span(cls="status-dot"), "Ready", cls="ready"), cls="chat-head"),
            Div(Div(*bubbles, id="messages", cls="messages"),
                Aside(H3("Activity"), P("AG-UI run and tool events appear here as the coworker works.", cls="muted"), Div(id="activity", cls="activity"), cls="activity-panel"), cls="chat-body"),
            Form(Textarea(name="message", id="composer", placeholder=f"Message {agent['name']}…", rows="1", required=True),
                 Input(type="hidden", name="channel_id", value=str(channel["id"])), Button("Send", type="submit", id="send-button", cls="send-button"),
                 id="chat-form", cls="composer"), cls="chat-shell"),
        Script(src="/static/chat.js"), title=f"{channel['title']} · FastBot")


def agents_page():
    agents = db.rows("SELECT * FROM agents ORDER BY id")
    return shell("/agents", topbar("COWORKERS", "Your AI team", "Create focused coworkers and give each only the access it needs."),
                 Div(*[agent_card(a) for a in agents], cls="agent-grid wide"))


def audit_page():
    events = db.rows("SELECT e.*,a.name agent_name FROM audit_events e LEFT JOIN agents a ON a.id=e.agent_id ORDER BY e.id DESC LIMIT 100")
    return shell("/admin/audit", topbar("GOVERNANCE", "Audit trail", "Every run, tool call, and policy decision in one readable record."),
                 Div(*[Div(Span(e["event_type"], cls="event-type"), Div(Strong(e["agent_name"] or "System"), Small(e["action"] or e["created_at"])),
                           Span(e["decision"] or "recorded", cls=f"pill {e['decision'] or ''}"), cls="audit-row") for e in events] or [Div("No activity yet.", cls="empty")], cls="audit-list"))


def boundaries_page():
    rules = db.rows("SELECT * FROM policies ORDER BY action,id")
    return shell("/admin/boundaries", topbar("GOVERNANCE", "Boundaries", "Deny rules win. Anything without an explicit allow fails closed."),
                 Div(*[Div(Span(r["effect"].upper(), cls=f"pill {r['effect']}"), Div(Strong(r["action"]), Code(r["pattern"]), Small(r["note"])), cls="rule-row") for r in rules], cls="rules"))


def skills_page():
    skills = db.rows("SELECT * FROM skills ORDER BY name")
    return shell("/skills", topbar("CAPABILITIES", "Skills", "Reusable instructions shape behavior; policies still govern every capability."),
                 Div(*[Div(H3(s["name"]), P(s["description"]), cls="panel") for s in skills] or [Div(H3("No personal skills yet"), P("Skills are instructions, never hidden capabilities."), cls="empty")]))
