from __future__ import annotations

from fasthtml.common import *

from . import db

NAV = (("⌂", "Home", "/"), ("✦", "Coworkers", "/agents"), ("⌁", "Skills", "/skills"),
       ("▣", "Computers", "/admin/computers"), ("◈", "Boundaries", "/admin/boundaries"),
       ("⌘", "Plugins", "/admin/plugins"), ("▤", "Components", "/admin/components"),
       ("◆", "Credentials", "/admin/credentials"), ("◎", "People", "/admin/people"),
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


def agent_card(agent, editable=False):
    edit = Details(Summary("Edit"), Form(Input(name="name", value=agent["name"], required=True), Input(name="title", value=agent["title"]), Textarea(agent["description"], name="description"), Textarea(agent["system_prompt"], name="system_prompt"), Input(name="endpoint", value=agent.get("endpoint") or "", placeholder="Remote AG-UI endpoint"), Select(Option("Private",value="private",selected=agent["visibility"]=="private"),Option("Public",value="public",selected=agent["visibility"]=="public"),name="visibility"),Button("Save",cls="button secondary"),method="post",action=f"/agents/{agent['id']}",cls="admin-form compact")) if editable else None
    return Article(
        Div(agent["icon"], cls="agent-icon"),
        Div(H3(agent["name"]), P(agent["title"], cls="muted"), P(agent["description"]), cls="agent-copy"),
        Div(A("Open channel", href=f"/agents/{agent['id']}/launch", cls="button secondary"), edit) if edit else A("Open channel", href=f"/agents/{agent['id']}/launch", cls="button secondary"), cls="agent-card")


def home_page(actor=None):
    agents = db.rows("SELECT * FROM agents WHERE deleted_at IS NULL ORDER BY id") if actor and actor.role=="admin" else db.rows("SELECT * FROM agents WHERE deleted_at IS NULL AND (visibility='public' OR owner_id=?) ORDER BY id",(actor.id if actor else 0,))
    channels = db.rows("SELECT c.*,a.name agent_name,a.icon FROM channels c JOIN agents a ON a.id=c.agent_id ORDER BY c.updated_at DESC LIMIT 8") if actor and actor.role=="admin" else db.rows("SELECT c.*,a.name agent_name,a.icon FROM channels c JOIN agents a ON a.id=c.agent_id WHERE c.owner_id=? ORDER BY c.updated_at DESC LIMIT 8",(actor.id if actor else 0,))
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


def agents_page(actor=None):
    agents = db.rows("SELECT * FROM agents WHERE deleted_at IS NULL ORDER BY id") if actor and actor.role=="admin" else db.rows("SELECT * FROM agents WHERE deleted_at IS NULL AND (visibility='public' OR owner_id=?) ORDER BY id",(actor.id if actor else 0,))
    form = Form(H3("Create coworker"), Input(name="name", placeholder="Name", required=True),
                Input(name="title", placeholder="Title"), Input(name="description", placeholder="Description"),
                Textarea(name="system_prompt", placeholder="Standing role and instructions", required=True),
                Input(name="endpoint", placeholder="Optional remote AG-UI endpoint"),
                Input(name="authorization", type="password", placeholder="Optional Authorization header (write-only)"),
                Select(Option("Private", value="private"), Option("Public", value="public"), name="visibility"),
                Button("Create coworker", cls="button"), method="post", action="/agents", cls="admin-form")
    return shell("/agents", topbar("COWORKERS", "Your AI team", "Local LangGraph and remote AG-UI coworkers share one governed workspace."),
                 Div(*[agent_card(a, editable=True) for a in agents], cls="agent-grid wide"), form)


def audit_page():
    events = db.rows("SELECT e.*,a.name agent_name FROM audit_events e LEFT JOIN agents a ON a.id=e.agent_id ORDER BY e.id DESC LIMIT 100")
    return shell("/admin/audit", topbar("GOVERNANCE", "Audit trail", "Every run, tool call, and policy decision in one readable record."),
                 Div(*[Div(Span(e["event_type"], cls="event-type"), Div(Strong(e["agent_name"] or "System"), Small(e["action"] or e["created_at"])),
                           Span(e["decision"] or "recorded", cls=f"pill {e['decision'] or ''}"), cls="audit-row") for e in events] or [Div("No activity yet.", cls="empty")], cls="audit-list"))


def boundaries_page():
    rules = db.rows("SELECT * FROM policies ORDER BY action,id")
    rows = [Div(Span(r["effect"].upper(), cls=f"pill {r['effect']}"), Div(Strong(r["action"]), Code(r["pattern"]), Small(r["note"])), Form(Button("Disable" if r["enabled"] else "Enable",cls="button secondary"),method="post",action=f"/admin/boundaries/{r['id']}/toggle",cls="inline"), cls="rule-row") for r in rules]
    form = Form(H3("Add policy rule"), Input(name="action", placeholder="browser.navigate", required=True),
                Select(Option("Deny", value="deny"), Option("Allow", value="allow"), name="effect"),
                Input(name="pattern", placeholder="https://example.com/*", required=True), Input(name="note", placeholder="Reason"),
                Button("Add rule", cls="button"), method="post", action="/admin/boundaries", cls="admin-form")
    return shell("/admin/boundaries", topbar("GOVERNANCE", "Boundaries", "Deny rules win. Anything without an explicit allow fails closed."),
                 Div(*rows, cls="rules"), form)


def skills_page(actor=None):
    skills = db.rows("SELECT * FROM skills ORDER BY name") if actor and actor.role=="admin" else db.rows("SELECT * FROM skills WHERE scope='deployment' OR owner_id=? ORDER BY name",(actor.id if actor else 0,))
    agents = db.rows("SELECT * FROM agents WHERE deleted_at IS NULL ORDER BY name") if actor and actor.role=="admin" else db.rows("SELECT * FROM agents WHERE deleted_at IS NULL AND owner_id=? ORDER BY name",(actor.id if actor else 0,))
    cards = []
    for skill in skills:
        granted={x["agent_id"] for x in db.rows("SELECT agent_id FROM agent_skill_grants WHERE skill_id=?",(skill["id"],))}
        grants = Div(*[Form(Button(("Revoke from " if a["id"] in granted else "Grant to ")+a["name"], cls="button secondary"), method="post", action=f"/skills/{skill['id']}/grant/{a['id']}", cls="inline") for a in agents], cls="grant-list")
        edit = Details(Summary("Edit instructions"), Form(Input(name="name",value=skill["name"]),Input(name="description",value=skill["description"]),Textarea(skill["instructions"],name="instructions"),Button("Save",cls="button secondary"),method="post",action=f"/skills/{skill['id']}",cls="admin-form compact"))
        cards.append(Div(H3(skill["name"]), P(skill["description"]), Small(skill["scope"]), grants, edit, cls="panel"))
    form = Form(H3("Create skill"), Input(name="name", placeholder="Skill name", required=True), Input(name="description", placeholder="Description"),
                Textarea(name="instructions", placeholder="Reusable instructions", required=True), Select(Option("Personal", value="personal"), Option("Deployment", value="deployment"), name="scope"),
                Button("Create skill", cls="button"), method="post", action="/skills", cls="admin-form")
    return shell("/skills", topbar("CAPABILITIES", "Skills", "Reusable instructions shape behavior; policies still govern every capability."),
                 Div(*(cards or [Div(H3("No personal skills yet"), P("Skills are instructions, never hidden capabilities."), cls="empty")]), cls="agent-grid"), form)


def computers_page():
    from .computers import inspect
    cards = []
    for agent in db.rows("SELECT * FROM agents WHERE deleted_at IS NULL ORDER BY id"):
        computer = inspect(agent["slug"])
        actions = Div(*[Form(Button(label, cls="button secondary"), method="post", action=f"/admin/computers/{agent['id']}/{action}", cls="inline") for action,label in (("start","Start"),("stop","Stop"),("take","Take control"),("release","Release"))], cls="grant-list")
        preview = Img(src=f"/api/computers/{agent['id']}/screen", alt="Live browser screen", cls="computer-screen interactive-screen" if computer.control=="human" else "computer-screen", loading="lazy", data_agent=str(agent["id"])) if computer.status == "running" else Div("Computer is stopped", cls="screen-placeholder")
        human_controls = Div(Input(placeholder="Type into focused field",cls="human-text",data_agent=str(agent["id"])),Button("Type",type="button",cls="button secondary human-type",data_agent=str(agent["id"])),Button("Enter",type="button",cls="button secondary human-enter",data_agent=str(agent["id"])),cls="human-controls") if computer.control=="human" else None
        cards.append(Div(H3(agent["name"]), P(Strong(computer.backend), " · ", computer.status, " · ", computer.control), P(computer.current_url or computer.workspace, cls="muted"), preview, human_controls, actions, cls="panel computer-card"))
    return shell("/admin/computers", topbar("RUNTIME", "Coworker computers", "Isolated browser profiles, live screenshots, and explicit human takeover."), Div(*cards, cls="agent-grid"),Script(src="/static/computer.js"))


def credentials_page(items):
    form = Form(H3("Store credential"), Input(name="name", placeholder="Credential name", required=True), Input(name="kind", placeholder="Kind", required=True),
                Input(name="value", type="password", placeholder="Secret value (write-only)", required=True), Button("Encrypt and store", cls="button"), method="post", action="/admin/credentials", cls="admin-form")
    listing = Div(*[Div(Strong(x["name"]), Small(f"{x['kind']} · updated {x['updated_at']}"), Span("Write-only", cls="pill allowed"), cls="audit-row") for x in items] or [Div("No credentials stored", cls="empty")], cls="audit-list")
    return shell("/admin/credentials", topbar("SECRETS", "Credentials", "Encrypted at rest and never returned by an API."), listing, form)


def components_page():
    items = db.rows("SELECT * FROM components ORDER BY name")
    agents = db.rows("SELECT * FROM agents WHERE deleted_at IS NULL")
    cards=[]
    for x in items:
        withheld={r["agent_id"] for r in db.rows("SELECT agent_id FROM component_withholds WHERE component_id=?",(x["id"],))}
        grants=Div(*[Form(Button(("Restore to " if a["id"] in withheld else "Withhold from ")+a["name"],cls="button secondary"),method="post",action=f"/admin/components/{x['id']}/withhold/{a['id']}",cls="inline") for a in agents],cls="grant-list")
        cards.append(Div(H3(x["title"]),Code(x["name"]),Span("Published" if x["published"] else "Draft",cls="pill allowed" if x["published"] else "pill"),Form(Button("Unpublish" if x["published"] else "Publish",cls="button secondary"),method="post",action=f"/admin/components/{x['id']}/publish",cls="inline"),grants,cls="panel"))
    listing=Div(*cards,cls="agent-grid")
    form = Form(H3("Create component"), Input(name="name", placeholder="component-name", required=True), Input(name="title", placeholder="Title", required=True),
                Textarea(name="schema_json", placeholder='{"field":"string"}'), Input(name="template", placeholder="Registered renderer name"),
                Label(Input(type="checkbox", name="published", value="1"), " Publish"), Button("Create component", cls="button"), method="post", action="/admin/components", cls="admin-form")
    return shell("/admin/components", topbar("GENERATIVE UI", "Components", "Only published, server-registered renderers may be selected by agents."), listing, form)


def plugins_page():
    plugins = db.rows("SELECT * FROM plugins ORDER BY name"); agents = db.rows("SELECT * FROM agents WHERE deleted_at IS NULL"); credentials=db.rows("SELECT id,name FROM credentials ORDER BY name")
    cards=[]
    for plugin in plugins:
        tools = db.rows("SELECT * FROM plugin_tools WHERE plugin_id=?", (plugin["id"],))
        tool_rows=[]
        for tool in tools:
            granted={x["agent_id"] for x in db.rows("SELECT agent_id FROM agent_tool_grants WHERE tool_id=?",(tool["id"],))}
            grants=Div(*[Form(Button(("Revoke " if a["id"] in granted else "Grant ")+a["name"], cls="button secondary"), method="post", action=f"/admin/plugins/tools/{tool['id']}/grant/{a['id']}", cls="inline") for a in agents], cls="grant-list")
            tool_rows.append(Div(Strong(tool["name"]), Small(tool["risk"]), grants, cls="tool-row"))
        add_tool=Form(Input(name="name", placeholder="Tool name", required=True), Input(name="description", placeholder="Description"), Textarea(name="input_schema", placeholder='{"type":"object","properties":{}}'), Select(Option("Read",value="read"),Option("Write",value="write"),name="risk"), Button("Add tool",cls="button secondary"), method="post",action=f"/admin/plugins/{plugin['id']}/tools",cls="admin-form compact")
        cards.append(Div(H3(plugin["name"]), P(plugin["endpoint"],cls="muted"),*tool_rows,add_tool,cls="panel"))
    form=Form(H3("Connect MCP server"),Input(name="name",placeholder="Plugin name",required=True),Input(name="endpoint",placeholder="https://…/mcp",required=True),Select(Option("No credential",value=""),*[Option(c["name"],value=str(c["id"])) for c in credentials],name="auth_credential_id"),Button("Connect",cls="button"),method="post",action="/admin/plugins",cls="admin-form")
    return shell("/admin/plugins",topbar("CONNECTORS","MCP plugins","Configure reviewed servers, classify tools, and grant them per coworker."),Div(*cards,cls="agent-grid"),form)


def people_page():
    people=db.rows("SELECT id,email,name,role,active,created_at FROM users ORDER BY id")
    listing=Div(*[Div(Div(Strong(x["name"]),Small(x["email"])),Span(x["role"],cls="pill allowed" if x["role"]=="admin" else "pill"),Form(Select(Option("Member",value="member"),Option("Administrator",value="admin"),name="role"),Button("Update",cls="button secondary"),method="post",action=f"/admin/people/{x['id']}/role",cls="inline"),cls="audit-row") for x in people],cls="audit-list")
    form=Form(H3("Add person"),Input(name="email",type="email",placeholder="Email",required=True),Input(name="name",placeholder="Name",required=True),Input(name="password",type="password",placeholder="Initial password"),Select(Option("Member",value="member"),Option("Administrator",value="admin"),name="role"),Button("Add person",cls="button"),method="post",action="/admin/people",cls="admin-form")
    return shell("/admin/people",topbar("ACCESS","People and roles","Administrators govern deployment settings; members run visible coworkers."),listing,form)


def login_page():
    return Title("Sign in · FastBot"), Main(Form(Div("F",cls="brand-mark"),H1("Sign in to FastBot"),Input(name="email",type="email",placeholder="Email",required=True),Input(name="password",type="password",placeholder="Password",required=True),Button("Sign in",cls="button"),method="post",action="/login",cls="login-card"),cls="login-shell")
