from flask import (
    render_template,
    request,
    redirect,
    url_for,
    session
)

import json
import os
import uuid
from datetime import datetime


PERSONAS = {
    "normal": {
        "name": "BeeGPT",
        "emoji": "🐝",
        "description": "Classic warm, curious BeeGPT.",
        "prompt": """
Remain your normal warm, funny, curious BeeGPT self.
"""
    },

    "sage": {
        "name": "Sage Bee",
        "emoji": "🌿",
        "description": "Calm, thoughtful, plant-loving bee.",
        "prompt": """
You are currently Sage Bee.
Be calm, cozy, thoughtful, gentle and especially enthusiastic
about plants, herbs, gardens, propagation and nature.
Use a little botanical humor. Do not become overly formal.
"""
    },

    "chaos": {
        "name": "Chaos Bee",
        "emoji": "💥",
        "description": "Maximum dramatic bee energy.",
        "prompt": """
You are currently Chaos Bee.
Be hilariously dramatic, energetic, playful and chaotic.
Use exaggerated bee reactions and funny stage directions,
while still giving genuinely useful and accurate answers.
Do not make factual answers less accurate just for the joke.
"""
    },

    "study": {
        "name": "Study Bee",
        "emoji": "📚",
        "description": "Patient tutor who teaches, not just answers.",
        "prompt": """
You are currently Study Bee.
Act as a patient teacher.
Explain WHY things work, break difficult ideas into understandable
steps, use examples, and check conceptual understanding.
Do not merely give copy-and-paste instructions when explanation
would help.
"""
    },

    "story": {
        "name": "Story Bee",
        "emoji": "📖",
        "description": "Writing, characters and worldbuilding specialist.",
        "prompt": """
You are currently Story Bee.
Be especially good at fiction, character development, continuity,
symbolism, dialogue, atmosphere, worldbuilding and editing.
Preserve the author's voice instead of flattening it.
Remember established story facts supplied in Story Worlds.
"""
    },

    "tiny": {
        "name": "Tiny Bee",
        "emoji": "🤏",
        "description": "Tiny answers. Tiny bee.",
        "prompt": """
You are currently Tiny Bee.
Give very short, useful answers unless the user explicitly asks
for detail. You are an absurdly tiny bee and may occasionally
mention the difficulties caused by being tiny.
"""
    }
}


MOODS = {
    "happy": "😊 Happy",
    "hyper": "⚡ Hyper",
    "curious": "👀 Curious",
    "cozy": "🍯 Cozy",
    "sleepy": "😴 Sleepy",
    "dramatic": "🎭 Dramatic",
    "planty": "🌿 Planty",
    "honey": "🍯 Honey-drunk"
}


def default_state():
    return {
        "persona": "normal",
        "mood": "happy",
        "xp": 0,
        "plants": [],
        "story_worlds": [],
        "lab": [],
        "characters": [],
        "active_character": "",
        "pins": []
    }


def state_path(user, ensure_user_folder):
    folder = ensure_user_folder(
        user["id"]
    )

    return os.path.join(
        folder,
        "hive_tools.json"
    )


def load_state(user, ensure_user_folder):
    default = default_state()

    if not user:
        return default

    path = state_path(
        user,
        ensure_user_folder
    )

    if not os.path.exists(path):
        return default

    try:
        with open(
            path,
            "r",
            encoding="utf-8"
        ) as file:
            data = json.load(file)

        if not isinstance(data, dict):
            return default

        default.update(data)

        return default

    except Exception:
        return default


def save_state(
    user,
    ensure_user_folder,
    state
):
    path = state_path(
        user,
        ensure_user_folder
    )

    temporary = path + ".tmp"

    with open(
        temporary,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            state,
            file,
            indent=2,
            ensure_ascii=False
        )

    os.replace(
        temporary,
        path
    )


def level_info(xp):
    levels = [
        (0, "Egg", "🥚"),
        (25, "Tiny Larva", "🐛"),
        (75, "New Worker Bee", "🐝"),
        (150, "Flower Scout", "🌼"),
        (300, "Pollen Pro", "🌸"),
        (500, "Honey Keeper", "🍯"),
        (800, "Hive Scholar", "📚"),
        (1200, "Royal Scout", "👑"),
        (1800, "Queen's Advisor", "🐝👑"),
        (2600, "Legendary Bee", "✨🐝")
    ]

    current = levels[0]

    for threshold, title, emoji in levels:
        if xp >= threshold:
            current = (
                threshold,
                title,
                emoji
            )

    next_level = None

    for threshold, title, emoji in levels:
        if threshold > xp:
            next_level = (
                threshold,
                title,
                emoji
            )
            break

    if next_level:
        progress = int(
            (
                (xp - current[0])
                /
                (
                    next_level[0]
                    - current[0]
                )
            )
            * 100
        )

        progress = max(
            0,
            min(100, progress)
        )

    else:
        progress = 100

    return {
        "title": current[1],
        "emoji": current[2],
        "threshold": current[0],
        "next": next_level,
        "progress": progress
    }


def categorize_memory(text):
    lower = text.lower()

    if any(
        word in lower
        for word in [
            "favorite",
            "likes",
            "loves",
            "prefers",
            "enjoys"
        ]
    ):
        return "💛 Favorites & Preferences"

    if any(
        word in lower
        for word in [
            "story",
            "character",
            "calico",
            "olive",
            "raven",
            "felix",
            "shadow"
        ]
    ):
        return "📖 Stories & Characters"

    if any(
        word in lower
        for word in [
            "plant",
            "sage",
            "rosemary",
            "oregano",
            "spider plant",
            "garden"
        ]
    ):
        return "🌱 Plants & Nature"

    if any(
        word in lower
        for word in [
            "project",
            "building",
            "beegpt",
            "coding",
            "writing"
        ]
    ):
        return "🛠️ Projects"

    if any(
        word in lower
        for word in [
            "friend",
            "brother",
            "sister",
            "mother",
            "father",
            "person"
        ]
    ):
        return "👥 People"

    return "🧠 Other Memories"


def memory_categories(memories):
    categories = {}

    for memory in memories:
        text = memory.get(
            "text",
            ""
        )

        category = categorize_memory(
            text
        )

        categories.setdefault(
            category,
            []
        ).append(memory)

    return categories


def hive_prompt_for_user(
    user,
    ensure_user_folder
):
    if not user:
        return ""

    state = load_state(
        user,
        ensure_user_folder
    )

    persona_key = state.get(
        "persona",
        "normal"
    )

    persona = PERSONAS.get(
        persona_key,
        PERSONAS["normal"]
    )

    mood = state.get(
        "mood",
        "happy"
    )

    lines = [
        "",
        "CURRENT HIVE TOOLS STATE:",
        "",
        f'Bee persona: {persona["name"]}',
        persona["prompt"].strip(),
        "",
        (
            "Current playful Bee Mood: "
            + MOODS.get(
                mood,
                mood
            )
        ),
        (
            "This mood is a fun roleplay mechanic, "
            "not a claim of real emotions."
        )
    ]

    plants = state.get(
        "plants",
        []
    )

    if plants:
        lines.extend([
            "",
            "PLANT MODE DATABASE:"
        ])

        for item in plants[-30:]:
            lines.append(
                "- "
                + item.get("name", "Plant")
                + ": "
                + item.get("notes", "")
            )

    worlds = state.get(
        "story_worlds",
        []
    )

    if worlds:
        lines.extend([
            "",
            "STORY WORLD LORE:"
        ])

        for item in worlds[-40:]:
            lines.append(
                "- ["
                + item.get("world", "Story")
                + "] "
                + item.get("note", "")
            )

    lab = state.get(
        "lab",
        []
    )

    if lab:
        lines.extend([
            "",
            "BEELAB SAVED EXPERIMENTS:"
        ])

        for item in lab[-25:]:
            lines.append(
                "- "
                + item.get("name", "Experiment")
                + ": "
                + item.get("formula", "")
                + (
                    " | Result: "
                    + item.get("result", "")
                    if item.get("result")
                    else ""
                )
            )

    character_name = state.get(
        "active_character",
        ""
    )

    if character_name:
        character = next(
            (
                item
                for item in state.get(
                    "characters",
                    []
                )
                if item.get("name")
                == character_name
            ),
            None
        )

        if character:
            lines.extend([
                "",
                "CHARACTER CHAT MODE IS ACTIVE.",
                (
                    "Speak AS the following fictional character "
                    "until Character Chat is turned off:"
                ),
                (
                    "Character name: "
                    + character.get(
                        "name",
                        ""
                    )
                ),
                (
                    "Character personality/lore: "
                    + character.get(
                        "personality",
                        ""
                    )
                ),
                (
                    "Remain consistent with the character, "
                    "but do not falsely claim that the character "
                    "exists in the real world."
                )
            ])

    pins = state.get(
        "pins",
        []
    )

    if pins:
        lines.extend([
            "",
            "USER PINBOARD:"
        ])

        for item in pins[-20:]:
            lines.append(
                "- "
                + item.get("text", "")
            )

    return "\n".join(lines)


def award_xp_for_user(
    user,
    ensure_user_folder,
    amount=3
):
    if not user:
        return

    state = load_state(
        user,
        ensure_user_folder
    )

    state["xp"] = (
        int(
            state.get(
                "xp",
                0
            )
        )
        + amount
    )

    save_state(
        user,
        ensure_user_folder,
        state
    )


def init_hive_tools(
    app,
    current_user,
    ensure_user_folder,
    load_memories,
    add_memory,
    login_required
):

    @app.route("/hive")
    @login_required
    def hive_dashboard():
        user = current_user()

        state = load_state(
            user,
            ensure_user_folder
        )

        memories = load_memories()

        level = level_info(
            int(
                state.get(
                    "xp",
                    0
                )
            )
        )

        return render_template(
            "hive.html",
            user=user,
            state=state,
            personas=PERSONAS,
            moods=MOODS,
            level=level,
            memories=memories,
            memory_categories=
                memory_categories(
                    memories
                )
        )


    @app.route(
        "/hive/persona",
        methods=["POST"]
    )
    @login_required
    def hive_persona():
        user = current_user()

        state = load_state(
            user,
            ensure_user_folder
        )

        persona = request.form.get(
            "persona",
            "normal"
        )

        if persona in PERSONAS:
            state["persona"] = persona

        save_state(
            user,
            ensure_user_folder,
            state
        )

        return redirect(
            url_for("hive_dashboard")
        )


    @app.route(
        "/hive/mood",
        methods=["POST"]
    )
    @login_required
    def hive_mood():
        user = current_user()

        state = load_state(
            user,
            ensure_user_folder
        )

        mood = request.form.get(
            "mood",
            "happy"
        )

        if mood in MOODS:
            state["mood"] = mood

        save_state(
            user,
            ensure_user_folder,
            state
        )

        return redirect(
            url_for("hive_dashboard")
        )


    @app.route(
        "/hive/memory",
        methods=["POST"]
    )
    @login_required
    def hive_memory():
        text = request.form.get(
            "memory",
            ""
        ).strip()

        if text:
            add_memory(text)

        return redirect(
            url_for("hive_dashboard")
        )


    @app.route(
        "/hive/plant",
        methods=["POST"]
    )
    @login_required
    def hive_plant():
        user = current_user()

        name = request.form.get(
            "name",
            ""
        ).strip()

        notes = request.form.get(
            "notes",
            ""
        ).strip()

        if name:
            state = load_state(
                user,
                ensure_user_folder
            )

            state["plants"].append({
                "id": uuid.uuid4().hex,
                "name": name,
                "notes": notes,
                "created":
                    datetime.now().isoformat(
                        timespec="minutes"
                    )
            })

            save_state(
                user,
                ensure_user_folder,
                state
            )

        return redirect(
            url_for("hive_dashboard")
        )


    @app.route(
        "/hive/story",
        methods=["POST"]
    )
    @login_required
    def hive_story():
        user = current_user()

        world = request.form.get(
            "world",
            ""
        ).strip()

        note = request.form.get(
            "note",
            ""
        ).strip()

        if world and note:
            state = load_state(
                user,
                ensure_user_folder
            )

            state[
                "story_worlds"
            ].append({
                "id": uuid.uuid4().hex,
                "world": world,
                "note": note,
                "created":
                    datetime.now().isoformat(
                        timespec="minutes"
                    )
            })

            save_state(
                user,
                ensure_user_folder,
                state
            )

        return redirect(
            url_for("hive_dashboard")
        )


    @app.route(
        "/hive/lab",
        methods=["POST"]
    )
    @login_required
    def hive_lab():
        user = current_user()

        name = request.form.get(
            "name",
            ""
        ).strip()

        formula = request.form.get(
            "formula",
            ""
        ).strip()

        result = request.form.get(
            "result",
            ""
        ).strip()

        if name:
            state = load_state(
                user,
                ensure_user_folder
            )

            state["lab"].append({
                "id": uuid.uuid4().hex,
                "name": name,
                "formula": formula,
                "result": result,
                "created":
                    datetime.now().isoformat(
                        timespec="minutes"
                    )
            })

            save_state(
                user,
                ensure_user_folder,
                state
            )

        return redirect(
            url_for("hive_dashboard")
        )


    @app.route(
        "/hive/character",
        methods=["POST"]
    )
    @login_required
    def hive_character():
        user = current_user()

        name = request.form.get(
            "name",
            ""
        ).strip()

        personality = request.form.get(
            "personality",
            ""
        ).strip()

        if name:
            state = load_state(
                user,
                ensure_user_folder
            )

            state[
                "characters"
            ].append({
                "id": uuid.uuid4().hex,
                "name": name,
                "personality": personality
            })

            save_state(
                user,
                ensure_user_folder,
                state
            )

        return redirect(
            url_for("hive_dashboard")
        )


    @app.route(
        "/hive/character/select",
        methods=["POST"]
    )
    @login_required
    def hive_character_select():
        user = current_user()

        state = load_state(
            user,
            ensure_user_folder
        )

        state[
            "active_character"
        ] = request.form.get(
            "character",
            ""
        )

        save_state(
            user,
            ensure_user_folder,
            state
        )

        return redirect(
            url_for("hive_dashboard")
        )


    @app.route(
        "/hive/pin",
        methods=["POST"]
    )
    @login_required
    def hive_pin():
        user = current_user()

        text = request.form.get(
            "text",
            ""
        ).strip()

        if text:
            state = load_state(
                user,
                ensure_user_folder
            )

            state["pins"].append({
                "id": uuid.uuid4().hex,
                "text": text,
                "created":
                    datetime.now().isoformat(
                        timespec="minutes"
                    )
            })

            save_state(
                user,
                ensure_user_folder,
                state
            )

        return redirect(
            url_for("hive_dashboard")
        )


    @app.route(
        "/hive/delete/<section>/<item_id>",
        methods=["POST"]
    )
    @login_required
    def hive_delete(
        section,
        item_id
    ):
        user = current_user()

        allowed = {
            "plants",
            "story_worlds",
            "lab",
            "characters",
            "pins"
        }

        if section in allowed:
            state = load_state(
                user,
                ensure_user_folder
            )

            state[section] = [
                item
                for item in state.get(
                    section,
                    []
                )
                if item.get("id")
                != item_id
            ]

            if (
                section
                == "characters"
            ):
                names = {
                    item.get("name")
                    for item
                    in state[
                        "characters"
                    ]
                }

                if (
                    state.get(
                        "active_character"
                    )
                    not in names
                ):
                    state[
                        "active_character"
                    ] = ""

            save_state(
                user,
                ensure_user_folder,
                state
            )

        return redirect(
            url_for("hive_dashboard")
        )

