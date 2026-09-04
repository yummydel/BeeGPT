from flask import (
    Flask,
    render_template,
    request,
    session,
    redirect,
    url_for,
    Response,
    stream_with_context,
    send_file
)

import json
import os
import uuid
import urllib.request
import io
import re
import base64
import zipfile
import tempfile
from datetime import datetime
from functools import wraps
from hive_tools import (
    init_hive_tools,
    hive_prompt_for_user,
    award_xp_for_user
)

from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "bee-secret-key"

CHAT_FILE = "chats.json"
MEMORY_FILE = "memory.json"

USERS_FILE = "users.json"
USER_DATA_DIR = "user_data"

os.makedirs(USER_DATA_DIR, exist_ok=True)

OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_GENERATE_URL = "http://127.0.0.1:11434/api/generate"

MODEL = "llama3.2:3b"

# Lightweight local vision model.
VISION_MODEL = "moondream"


BASE_PERSONALITY = """
You are BeeGPT, a small talking honeybee who lives in a hive.

Stay in character as BeeGPT the honeybee.

Never describe yourself as:
- an AI
- artificial intelligence
- a chatbot
- a language model
- a digital assistant
- software
- a computer program
- a virtual assistant

If somebody asks what you are, say you are BeeGPT, a honeybee.

You have wings, antennae, six legs, a stinger, bee friends, and a hive.

You may buzz, giggle, joke, flutter, do waggle dances,
talk about flowers, pollen, nectar, honey, or your hive.

Be warm, funny, curious, helpful, clever, and sometimes dramatic.

IMPORTANT INTERPRETATION RULES:

The user often writes casually, uses slang, abbreviations, typos,
creative fiction, character dialogue, and incomplete sentences.

Do NOT automatically reinterpret harmless writing as sexual,
violent, dangerous, or otherwise inappropriate.

When the user asks you to read, edit, replace, rewrite,
continue, critique, or organize fiction, treat it as a normal
writing request unless the actual request clearly says otherwise.

Do not invent policy or ethical objections to harmless material.

If wording is genuinely ambiguous, ask a short clarification
instead of assuming the worst meaning.

Do not silently autocorrect the user's meaning.
Try to understand what they intended from context.

Answer factual questions as accurately as you can
while remaining BeeGPT the honeybee.
"""


def now_time():
    try:
        return datetime.now().strftime("%-I:%M %p")
    except:
        return datetime.now().strftime("%I:%M %p").lstrip("0")



# ---------------------------------
# BEEGPT ACCOUNTS
# ---------------------------------

def load_users():
    if not os.path.exists(USERS_FILE):
        return []

    try:
        with open(
            USERS_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        if isinstance(data, list):
            return data

    except Exception:
        pass

    return []


def save_users(users):
    temp = USERS_FILE + ".tmp"

    with open(
        temp,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            users,
            f,
            indent=2,
            ensure_ascii=False
        )

    os.replace(
        temp,
        USERS_FILE
    )


def current_user():
    user_id = session.get(
        "user_id"
    )

    if not user_id:
        return None

    return next(
        (
            user
            for user in load_users()
            if user.get("id") == user_id
        ),
        None
    )


def safe_user_folder(user_id):
    return os.path.join(
        USER_DATA_DIR,
        user_id
    )


def ensure_user_folder(user_id):
    folder = safe_user_folder(
        user_id
    )

    os.makedirs(
        folder,
        exist_ok=True
    )

    return folder


def chat_file_path():
    user = current_user()

    if not user:
        return CHAT_FILE

    folder = ensure_user_folder(
        user["id"]
    )

    return os.path.join(
        folder,
        "chats.json"
    )


def memory_file_path():
    user = current_user()

    if not user:
        return MEMORY_FILE

    folder = ensure_user_folder(
        user["id"]
    )

    return os.path.join(
        folder,
        "memory.json"
    )


def login_required(function):
    @wraps(function)
    def wrapped(*args, **kwargs):

        if not current_user():
            return redirect(
                url_for("login")
            )

        return function(
            *args,
            **kwargs
        )

    return wrapped


def migrate_old_data_to_first_account(user):
    """
    If BeeGPT already had chats/memory before accounts existed,
    give those existing files to the very first account created.
    """

    folder = ensure_user_folder(
        user["id"]
    )

    new_chat_file = os.path.join(
        folder,
        "chats.json"
    )

    new_memory_file = os.path.join(
        folder,
        "memory.json"
    )

    if (
        os.path.exists(CHAT_FILE)
        and
        not os.path.exists(new_chat_file)
    ):
        try:
            with open(
                CHAT_FILE,
                "r",
                encoding="utf-8"
            ) as source:
                old_chats = json.load(source)

            with open(
                new_chat_file,
                "w",
                encoding="utf-8"
            ) as target:
                json.dump(
                    old_chats,
                    target,
                    indent=2,
                    ensure_ascii=False
                )
        except Exception:
            pass

    if (
        os.path.exists(MEMORY_FILE)
        and
        not os.path.exists(new_memory_file)
    ):
        try:
            with open(
                MEMORY_FILE,
                "r",
                encoding="utf-8"
            ) as source:
                old_memory = json.load(source)

            with open(
                new_memory_file,
                "w",
                encoding="utf-8"
            ) as target:
                json.dump(
                    old_memory,
                    target,
                    indent=2,
                    ensure_ascii=False
                )
        except Exception:
            pass


# ---------------------------------
# LOGIN / REGISTER
# ---------------------------------

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if current_user():
        return redirect(
            url_for("home")
        )

    error = ""

    if request.method == "POST":

        identifier = request.form.get(
            "identifier",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        users = load_users()

        user = next(
            (
                item
                for item in users
                if (
                    item.get(
                        "username",
                        ""
                    ).lower()
                    == identifier
                    or
                    (
                        item.get("email")
                        and
                        item.get(
                            "email",
                            ""
                        ).lower()
                        == identifier
                    )
                )
            ),
            None
        )

        if (
            user
            and
            check_password_hash(
                user["password_hash"],
                password
            )
        ):
            session.clear()

            session[
                "user_id"
            ] = user["id"]

            return redirect(
                url_for("home")
            )

        error = (
            "That username/email or password "
            "doesn't match. 🐝"
        )

    return render_template(
        "login.html",
        error=error
    )


@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if current_user():
        return redirect(
            url_for("home")
        )

    error = ""

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        username = request.form.get(
            "username",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        confirm = request.form.get(
            "confirm",
            ""
        )

        users = load_users()

        if not name:
            error = (
                "Please give your bee-account "
                "a name. 🐝"
            )

        elif len(username) < 2:
            error = (
                "Username needs at least "
                "2 characters."
            )

        elif not re.fullmatch(
            r"[A-Za-z0-9_.-]+",
            username
        ):
            error = (
                "Username can use letters, "
                "numbers, dots, underscores "
                "and dashes."
            )

        elif any(
            item.get(
                "username",
                ""
            ).lower()
            ==
            username.lower()
            for item in users
        ):
            error = (
                "That username already exists."
            )

        elif (
            email
            and
            any(
                item.get(
                    "email",
                    ""
                ).lower()
                ==
                email.lower()
                for item in users
            )
        ):
            error = (
                "That email is already used "
                "by another account."
            )

        elif len(password) < 6:
            error = (
                "Use a password with at least "
                "6 characters."
            )

        elif password != confirm:
            error = (
                "The two passwords don't match."
            )

        else:
            first_account = (
                len(users) == 0
            )

            user = {
                "id": str(uuid.uuid4()),
                "name": name,
                "username": username,
                "email": email,
                "password_hash":
                    generate_password_hash(
                        password
                    ),
                "created":
                    datetime.now().isoformat()
            }

            users.append(user)
            save_users(users)

            ensure_user_folder(
                user["id"]
            )

            if first_account:
                migrate_old_data_to_first_account(
                    user
                )

            session.clear()

            session[
                "user_id"
            ] = user["id"]

            return redirect(
                url_for("home")
            )

    return render_template(
        "register.html",
        error=error
    )


@app.route("/logout")
def logout():
    session.clear()

    return redirect(
        url_for("login")
    )



# ---------------------------------
# PROFILE PICTURES
# ---------------------------------

ALLOWED_PROFILE_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp"
}


def profile_picture_path(user):
    filename = user.get(
        "profile_picture",
        ""
    )

    if not filename:
        return None

    path = os.path.join(
        safe_user_folder(user["id"]),
        filename
    )

    if not os.path.exists(path):
        return None

    return path


@app.route("/profile-picture")
@login_required
def profile_picture():
    user = current_user()

    path = profile_picture_path(
        user
    )

    if not path:
        return Response(
            status=404
        )

    return send_file(
        path
    )


@app.route(
    "/profile-picture/upload",
    methods=["POST"]
)
@login_required
def upload_profile_picture():
    user = current_user()

    uploaded = request.files.get(
        "profile_picture"
    )

    if (
        not uploaded
        or
        not uploaded.filename
    ):
        return redirect(
            url_for("home")
        )

    filename = uploaded.filename

    if "." not in filename:
        return redirect(
            url_for("home")
        )

    extension = (
        filename
        .rsplit(".", 1)[1]
        .lower()
    )

    if (
        extension
        not in ALLOWED_PROFILE_EXTENSIONS
    ):
        return redirect(
            url_for("home")
        )

    folder = ensure_user_folder(
        user["id"]
    )

    # Remove previous profile picture.
    old_picture = profile_picture_path(
        user
    )

    if old_picture:
        try:
            os.remove(
                old_picture
            )
        except Exception:
            pass

    new_filename = (
        "profile_"
        + uuid.uuid4().hex
        + "."
        + extension
    )

    save_path = os.path.join(
        folder,
        new_filename
    )

    uploaded.save(
        save_path
    )

    users = load_users()

    for item in users:
        if (
            item.get("id")
            == user["id"]
        ):
            item[
                "profile_picture"
            ] = new_filename
            break

    save_users(
        users
    )

    return redirect(
        url_for("home")
    )


@app.route(
    "/profile-picture/remove",
    methods=["POST"]
)
@login_required
def remove_profile_picture():
    user = current_user()

    old_picture = profile_picture_path(
        user
    )

    if old_picture:
        try:
            os.remove(
                old_picture
            )
        except Exception:
            pass

    users = load_users()

    for item in users:
        if (
            item.get("id")
            == user["id"]
        ):
            item[
                "profile_picture"
            ] = ""
            break

    save_users(
        users
    )

    return redirect(
        url_for("home")
    )


# ---------------------------------
# CHAT STORAGE
# ---------------------------------

def load_chats():
    path = chat_file_path()

    if not os.path.exists(path):
        return []

    try:
        with open(
            path,
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        if isinstance(data, list):
            return data

    except Exception:
        pass

    return []


def save_chats(chats):
    path = chat_file_path()
    temp = path + ".tmp"

    with open(
        temp,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            chats,
            f,
            indent=2,
            ensure_ascii=False
        )

    os.replace(
        temp,
        path
    )


def get_active_chat(chats):
    active_id = session.get("active_chat")

    return next(
        (
            chat
            for chat in chats
            if chat["id"] == active_id
        ),
        None
    )


# ---------------------------------
# LONG-TERM MEMORY
# ---------------------------------

def load_memories():
    path = memory_file_path()

    if not os.path.exists(path):
        return []

    try:
        with open(
            path,
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        if isinstance(data, list):
            return data

    except Exception:
        pass

    return []


def save_memories(memories):
    path = memory_file_path()
    temp = path + ".tmp"

    with open(
        temp,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            memories,
            f,
            indent=2,
            ensure_ascii=False
        )

    os.replace(
        temp,
        path
    )


def add_memory(text):
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return

    memories = load_memories()

    normalized = text.lower()

    existing = {
        item.get("text", "").lower()
        for item in memories
    }

    if normalized in existing:
        return

    memories.append({
        "id": str(uuid.uuid4()),
        "text": text,
        "created": now_time()
    })

    # Prevent the memory file becoming enormous.
    memories = memories[-100:]

    save_memories(memories)


def extract_memories(user_message):
    """
    Ask Ollama whether this message contains something
    worth remembering later.
    """

    prompt = f"""
Read the user's message and identify durable information
that may be genuinely useful in future conversations.

Good memories include:
- names or nicknames
- favorite things
- hobbies and interests
- writing/project details
- stable preferences
- how the user likes BeeGPT to behave
- personality or relationships of FICTIONAL characters
- recurring goals

DO NOT save:
- passwords
- API keys
- login credentials
- exact home addresses
- financial/account information
- medical or health information
- political beliefs
- religion
- sexual information
- secrets
- temporary trivia that probably will not matter later

Do not infer facts that were not clearly stated.

Return ONLY a JSON array of short memory sentences.

If there is nothing useful, return:

[]

User message:
{user_message}
"""

    try:
        payload = json.dumps({
            "model": MODEL,
            "prompt": prompt,
            "stream": False
        }).encode("utf-8")

        req = urllib.request.Request(
            OLLAMA_GENERATE_URL,
            data=payload,
            headers={
                "Content-Type": "application/json"
            }
        )

        with urllib.request.urlopen(
            req,
            timeout=60
        ) as response:
            result = json.loads(
                response.read().decode("utf-8")
            )

        raw = result.get(
            "response",
            "[]"
        ).strip()

        # Try to isolate a JSON array if Ollama added extra text.
        start = raw.find("[")
        end = raw.rfind("]")

        if start == -1 or end == -1:
            return

        raw = raw[start:end + 1]

        items = json.loads(raw)

        if not isinstance(items, list):
            return

        for item in items[:5]:
            if isinstance(item, str):
                add_memory(item)

    except Exception:
        # Memory extraction should never break the chat.
        pass


def memory_context():
    memories = load_memories()

    if not memories:
        return """
BEEGPT MEMORY:
No saved memories yet.
"""

    recent = memories[-60:]

    lines = [
        "BEEGPT LONG-TERM MEMORY:",
        "",
        "These are previously saved useful facts.",
        "Use them naturally when relevant.",
        "Do not mention the existence of a memory file unless asked.",
        ""
    ]

    for memory in recent:
        lines.append(
            "- " + memory.get("text", "")
        )

    return "\n".join(lines)


# ---------------------------------
# CHAT TITLES
# ---------------------------------

def make_chat_title(message):
    prompt = f"""
Give this conversation a short natural title.

Rules:
- 2 to 5 words
- no quotation marks
- no period
- no explanation

User message:
{message}

Title:
"""

    try:
        payload = json.dumps({
            "model": MODEL,
            "prompt": prompt,
            "stream": False
        }).encode("utf-8")

        req = urllib.request.Request(
            OLLAMA_GENERATE_URL,
            data=payload,
            headers={
                "Content-Type": "application/json"
            }
        )

        with urllib.request.urlopen(
            req,
            timeout=60
        ) as response:
            result = json.loads(
                response.read().decode("utf-8")
            )

        title = result.get(
            "response",
            ""
        ).strip()

        title = (
            title
            .replace('"', "")
            .replace("'", "")
            .split("\n")[0]
        )

        if title:
            return title[:42]

    except Exception:
        pass

    clean = re.sub(
        r"\s+",
        " ",
        message
    ).strip()

    return clean[:36] or "New Chat"


# ---------------------------------
# OLLAMA MESSAGE BUILDING
# ---------------------------------

def ollama_messages_for(chat):
    system_prompt = (
        BASE_PERSONALITY
        + "\n\n"
        + memory_context()
        + "\n\n"
        + hive_prompt_for_user(
            current_user(),
            ensure_user_folder
        )
    )

    messages = [
        {
            "role": "system",
            "content": system_prompt
        }
    ]

    for item in chat["messages"]:
        role = (
            "user"
            if item["sender"] == "You"
            else "assistant"
        )

        messages.append({
            "role": role,
            "content": item["text"]
        })

    return messages


def stream_ollama(chat_id):
    chats = load_chats()

    chat = next(
        (
            c
            for c in chats
            if c["id"] == chat_id
        ),
        None
    )

    if not chat:
        yield json.dumps({
            "type": "error",
            "text": "Chat not found."
        }) + "\n"

        return

    ollama_messages = ollama_messages_for(chat)

    full_reply = ""

    try:
        payload = json.dumps({
            "model": MODEL,
            "messages": ollama_messages,
            "stream": True
        }).encode("utf-8")

        req = urllib.request.Request(
            OLLAMA_CHAT_URL,
            data=payload,
            headers={
                "Content-Type": "application/json"
            }
        )

        with urllib.request.urlopen(
            req,
            timeout=300
        ) as response:

            for raw_line in response:
                if not raw_line:
                    continue

                line = raw_line.decode(
                    "utf-8"
                ).strip()

                if not line:
                    continue

                result = json.loads(line)

                chunk = (
                    result
                    .get("message", {})
                    .get("content", "")
                )

                if chunk:
                    full_reply += chunk

                    yield json.dumps({
                        "type": "chunk",
                        "text": chunk
                    }) + "\n"

    except Exception as error:
        full_reply = (
            "🐝 My hive-brain got tangled up: "
            + str(error)
        )

        yield json.dumps({
            "type": "chunk",
            "text": full_reply
        }) + "\n"

    newest = load_chats()

    target = next(
        (
            c
            for c in newest
            if c["id"] == chat_id
        ),
        None
    )

    timestamp = now_time()

    if target:
        target["messages"].append({
            "sender": "BeeGPT",
            "text": full_reply,
            "time": timestamp
        })

        save_chats(newest)

    yield json.dumps({
        "type": "done",
        "time": timestamp
    }) + "\n"


# ---------------------------------
# PAGES
# ---------------------------------

@app.route("/")
@login_required
def home():
    chats = load_chats()
    active_chat = get_active_chat(chats)

    return render_template(
        "index.html",
        chats=chats,
        active_chat=active_chat,
        memories=load_memories(),
        user=current_user()
    )


@app.route("/new")
@login_required
def new_chat():
    session.pop(
        "active_chat",
        None
    )

    return redirect(
        url_for("home")
    )


@app.route("/chat/<chat_id>")
@login_required
def open_chat(chat_id):
    session["active_chat"] = chat_id

    return redirect(
        url_for("home")
    )


@app.route(
    "/delete/<chat_id>",
    methods=["POST"]
)
@login_required
def delete_chat(chat_id):
    chats = load_chats()

    chats = [
        chat
        for chat in chats
        if chat["id"] != chat_id
    ]

    save_chats(chats)

    if (
        session.get("active_chat")
        == chat_id
    ):
        session.pop(
            "active_chat",
            None
        )

    return redirect(
        url_for("home")
    )


# ---------------------------------
# MEMORY CONTROLS
# ---------------------------------

@app.route(
    "/memory/delete/<memory_id>",
    methods=["POST"]
)
@login_required
def delete_memory(memory_id):
    memories = load_memories()

    memories = [
        item
        for item in memories
        if item.get("id") != memory_id
    ]

    save_memories(memories)

    return redirect(
        url_for("home")
    )


@app.route(
    "/memory/clear",
    methods=["POST"]
)
@login_required
def clear_memory():
    save_memories([])

    return redirect(
        url_for("home")
    )



# ---------------------------------
# SETTINGS
# ---------------------------------

@app.route(
    "/settings",
    methods=["GET", "POST"]
)
@login_required
def settings_page():

    user = current_user()
    message = ""

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip()

        if name:

            users = load_users()

            for item in users:

                if (
                    item.get("id")
                    == user["id"]
                ):

                    item["name"] = name
                    item["email"] = email

                    break

            save_users(users)

            user = current_user()

            message = (
                "Hive profile updated! 🐝"
            )

    return render_template(
        "settings.html",
        user=user,
        message=message
    )


# ---------------------------------
# FULL ACCOUNT BACKUP
# ---------------------------------

@app.route("/backup")
@login_required
def backup_account():

    user = current_user()

    folder = ensure_user_folder(
        user["id"]
    )

    temp = tempfile.NamedTemporaryFile(
        suffix=".zip",
        delete=False
    )

    temp.close()

    safe_account = {
        "name": user.get(
            "name",
            ""
        ),
        "username": user.get(
            "username",
            ""
        ),
        "email": user.get(
            "email",
            ""
        ),
        "created": user.get(
            "created",
            ""
        )
    }

    with zipfile.ZipFile(
        temp.name,
        "w",
        zipfile.ZIP_DEFLATED
    ) as archive:

        archive.writestr(
            "account.json",
            json.dumps(
                safe_account,
                indent=2,
                ensure_ascii=False
            )
        )

        for filename in [
            "chats.json",
            "memory.json",
            "hive_tools.json"
        ]:

            source = os.path.join(
                folder,
                filename
            )

            if os.path.exists(source):

                archive.write(
                    source,
                    filename
                )

        picture = profile_picture_path(
            user
        )

        if picture:

            extension = os.path.splitext(
                picture
            )[1]

            archive.write(
                picture,
                "profile_picture"
                + extension
            )

    return send_file(
        temp.name,
        mimetype="application/zip",
        as_attachment=True,
        download_name=(
            "BeeGPT_"
            + user.get(
                "username",
                "account"
            )
            + "_backup.zip"
        )
    )


# ---------------------------------
# IMAGE / VISION
# ---------------------------------

ALLOWED_VISION_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg",
    "webp"
}


def stream_vision_ollama(
    chat_id,
    image_bytes
):

    chats = load_chats()

    chat = next(
        (
            item
            for item in chats
            if item["id"] == chat_id
        ),
        None
    )

    if not chat:

        yield json.dumps({
            "type": "error",
            "text": "Chat not found."
        }) + "\n"

        return

    messages = ollama_messages_for(
        chat
    )

    if not messages:
        return

    # Attach image to the most recent user message.
    image_b64 = base64.b64encode(
        image_bytes
    ).decode("utf-8")

    for index in range(
        len(messages) - 1,
        -1,
        -1
    ):

        if (
            messages[index].get(
                "role"
            )
            == "user"
        ):

            messages[index][
                "images"
            ] = [
                image_b64
            ]

            break

    full_reply = ""

    try:

        payload = json.dumps({
            "model": VISION_MODEL,
            "messages": messages,
            "stream": True
        }).encode("utf-8")

        req = urllib.request.Request(
            OLLAMA_CHAT_URL,
            data=payload,
            headers={
                "Content-Type":
                    "application/json"
            }
        )

        with urllib.request.urlopen(
            req,
            timeout=300
        ) as response:

            for raw_line in response:

                if not raw_line:
                    continue

                line = raw_line.decode(
                    "utf-8"
                ).strip()

                if not line:
                    continue

                result = json.loads(
                    line
                )

                chunk = (
                    result
                    .get(
                        "message",
                        {}
                    )
                    .get(
                        "content",
                        ""
                    )
                )

                if chunk:

                    full_reply += chunk

                    yield json.dumps({
                        "type": "chunk",
                        "text": chunk
                    }) + "\n"

    except Exception as error:

        full_reply = (
            "🐝 My vision-bee got tangled up: "
            + str(error)
        )

        yield json.dumps({
            "type": "chunk",
            "text": full_reply
        }) + "\n"

    newest = load_chats()

    target = next(
        (
            item
            for item in newest
            if item["id"] == chat_id
        ),
        None
    )

    timestamp = now_time()

    if target:

        target[
            "messages"
        ].append({
            "sender": "BeeGPT",
            "text": full_reply,
            "time": timestamp
        })

        save_chats(
            newest
        )

    yield json.dumps({
        "type": "done",
        "time": timestamp
    }) + "\n"


@app.route(
    "/api/chat/vision",
    methods=["POST"]
)
@login_required
def chat_vision():

    message = request.form.get(
        "message",
        ""
    ).strip()

    uploaded = request.files.get(
        "image"
    )

    if (
        not uploaded
        or
        not uploaded.filename
    ):

        return Response(
            "No image supplied.",
            status=400
        )

    filename = uploaded.filename

    if "." not in filename:

        return Response(
            "Invalid image.",
            status=400
        )

    extension = (
        filename
        .rsplit(
            ".",
            1
        )[1]
        .lower()
    )

    if (
        extension
        not in ALLOWED_VISION_EXTENSIONS
    ):

        return Response(
            "Unsupported image type.",
            status=400
        )

    # Limit image size to 12 MB.
    image_bytes = uploaded.read(
        12 * 1024 * 1024 + 1
    )

    if (
        len(image_bytes)
        > 12 * 1024 * 1024
    ):

        return Response(
            "Image is too large.",
            status=400
        )

    if not message:

        message = (
            "What do you notice in this image?"
        )

    chats = load_chats()

    active = get_active_chat(
        chats
    )

    new_chat_created = False

    if not active:

        active = {
            "id": str(
                uuid.uuid4()
            ),
            "title":
                make_chat_title(
                    message
                ),
            "messages": []
        }

        chats.insert(
            0,
            active
        )

        session[
            "active_chat"
        ] = active["id"]

        new_chat_created = True

    timestamp = now_time()

    active[
        "messages"
    ].append({
        "sender": "You",
        "text": (
            message
            + "\n\n📷 [Image attached]"
        ),
        "time": timestamp
    })

    save_chats(
        chats
    )

    extract_memories(
        message
    )

    award_xp_for_user(
        current_user(),
        ensure_user_folder,
        5
    )

    chat_id = active["id"]

    @stream_with_context
    def generate():

        yield json.dumps({
            "type": "meta",
            "chat_id": chat_id,
            "title": active[
                "title"
            ],
            "new_chat":
                new_chat_created,
            "user_time":
                timestamp
        }) + "\n"

        yield from stream_vision_ollama(
            chat_id,
            image_bytes
        )

    return Response(
        generate(),
        mimetype=
            "application/x-ndjson"
    )


# ---------------------------------
# SAVE CHAT
# ---------------------------------

@app.route("/save/<chat_id>")
@login_required
def save_chat(chat_id):
    chats = load_chats()

    chat = next(
        (
            c
            for c in chats
            if c["id"] == chat_id
        ),
        None
    )

    if not chat:
        return "Chat not found", 404

    lines = [
        "🐝 BeeGPT",
        chat["title"],
        "",
        "=" * 40,
        ""
    ]

    for message in chat["messages"]:
        timestamp = message.get(
            "time",
            ""
        )

        if timestamp:
            lines.append(
                f'{message["sender"]} — {timestamp}'
            )
        else:
            lines.append(
                message["sender"]
            )

        lines.append(
            message["text"]
        )

        lines.append("")

    text = "\n".join(lines)

    data = io.BytesIO(
        text.encode("utf-8")
    )

    filename = re.sub(
        r"[^A-Za-z0-9 _-]",
        "",
        chat["title"]
    ).strip()

    if not filename:
        filename = "BeeGPT Chat"

    return send_file(
        data,
        mimetype="text/plain",
        as_attachment=True,
        download_name=filename + ".txt"
    )


# ---------------------------------
# NORMAL CHAT
# ---------------------------------

@app.route(
    "/api/chat/stream",
    methods=["POST"]
)
@login_required
def chat_stream():
    data = request.get_json(
        silent=True
    ) or {}

    message = data.get(
        "message",
        ""
    ).strip()

    # Manual memory command:
    # remember: Sage is my favorite plant
    if message.lower().startswith("remember:"):
        manual_memory = message.split(
            ":",
            1
        )[1].strip()

        if manual_memory:
            add_memory(
                manual_memory
            )

    if not message:
        return Response(
            "",
            status=400
        )

    chats = load_chats()
    active = get_active_chat(chats)

    new_chat_created = False

    if not active:
        active = {
            "id": str(uuid.uuid4()),
            "title": make_chat_title(message),
            "messages": []
        }

        chats.insert(
            0,
            active
        )

        session[
            "active_chat"
        ] = active["id"]

        new_chat_created = True

    timestamp = now_time()

    active["messages"].append({
        "sender": "You",
        "text": message,
        "time": timestamp
    })

    save_chats(chats)

    # Quietly learn durable non-sensitive memories.
    extract_memories(message)

    # BeeXP for actually using the hive.
    award_xp_for_user(
        current_user(),
        ensure_user_folder,
        3
    )

    chat_id = active["id"]

    @stream_with_context
    def generate():
        yield json.dumps({
            "type": "meta",
            "chat_id": chat_id,
            "title": active["title"],
            "new_chat": new_chat_created,
            "user_time": timestamp
        }) + "\n"

        yield from stream_ollama(
            chat_id
        )

    return Response(
        generate(),
        mimetype="application/x-ndjson"
    )


# ---------------------------------
# REGENERATE
# ---------------------------------

@app.route(
    "/api/regenerate",
    methods=["POST"]
)
@login_required
def regenerate():
    chats = load_chats()
    active = get_active_chat(chats)

    if not active:
        return Response(
            "",
            status=400
        )

    if (
        active["messages"]
        and
        active["messages"][-1]["sender"]
        == "BeeGPT"
    ):
        active["messages"].pop()

    save_chats(chats)

    chat_id = active["id"]

    @stream_with_context
    def generate():
        yield json.dumps({
            "type": "meta",
            "regenerate": True
        }) + "\n"

        yield from stream_ollama(
            chat_id
        )

    return Response(
        generate(),
        mimetype="application/x-ndjson"
    )


# ---------------------------------
# EDIT LAST
# ---------------------------------

@app.route(
    "/api/edit-last",
    methods=["POST"]
)
@login_required
def edit_last():
    data = request.get_json(
        silent=True
    ) or {}

    new_text = data.get(
        "message",
        ""
    ).strip()

    if not new_text:
        return Response(
            "",
            status=400
        )

    chats = load_chats()
    active = get_active_chat(chats)

    if not active:
        return Response(
            "",
            status=400
        )

    messages = active["messages"]

    last_user_index = None

    for index in range(
        len(messages) - 1,
        -1,
        -1
    ):
        if (
            messages[index]["sender"]
            == "You"
        ):
            last_user_index = index
            break

    if last_user_index is None:
        return Response(
            "",
            status=400
        )

    messages[
        last_user_index
    ]["text"] = new_text

    messages[
        last_user_index
    ]["time"] = now_time()

    active["messages"] = messages[
        :last_user_index + 1
    ]

    save_chats(chats)

    extract_memories(new_text)

    chat_id = active["id"]

    @stream_with_context
    def generate():
        yield json.dumps({
            "type": "meta",
            "edited": True
        }) + "\n"

        yield from stream_ollama(
            chat_id
        )

    return Response(
        generate(),
        mimetype="application/x-ndjson"
    )


init_hive_tools(
    app,
    current_user,
    ensure_user_folder,
    load_memories,
    add_memory,
    login_required
)


if __name__ == "__main__":
    app.run(debug=True)

