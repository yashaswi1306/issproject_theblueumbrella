from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles 
from pydantic import BaseModel
import pymysql
import pymysql.cursors
from pymongo import MongoClient
import os
import secrets
from datetime import datetime,timedelta
from dotenv import load_dotenv
from utils.facial_recognition_module import find_closest_match, build_encodings_cache
from fastapi import WebSocket, WebSocketDisconnect
import uuid
from manager import ConnectionManager


import pickle

CACHE_FILE = "encodings_cache.pkl"

def save_cache(cache):
    with open(CACHE_FILE, "wb") as f:
        pickle.dump(cache, f)
    print("Cache saved to disk.")

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "rb") as f:
            cache = pickle.load(f)
        print(f"Cache loaded from disk: {len(cache)} records.")
        return cache
    return None



load_dotenv()
sessions = {}
app = FastAPI()

@app.on_event("startup")
async def startup():
    global encodings_cache
    
 
    cached = load_cache()
    if cached:
        encodings_cache = cached
        return
    
    mongo = access_mongo()
    db_images = {}
    for doc in mongo["images"].find({}, {"uid": 1, "image": 1}):
        db_images[doc["uid"]] = doc["image"]
    encodings_cache = build_encodings_cache(db_images)
    save_cache(encodings_cache)

encodings_cache = {}
manager = ConnectionManager()

def access_sql_database():
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST","localhost"),
        user=os.getenv("MYSQL_USER","root"),
        password=os.getenv("MYSQL_PASSWORD",""),
        database=os.getenv("MYSQL_DB","arena_db"),
        cursorclass=pymysql.cursors.DictCursor
    )

def access_mongo():
    client=MongoClient(os.getenv("MONGO_URI","mongodb://localhost:27017/"))
    return client["arena_db"]

def current_user(request:Request):
    session_id=request.cookies.get("session_id")
    if not session_id or session_id not in sessions:
        return None
    session=sessions[session_id]
    if (session["expires"]<datetime.utcnow()):
        sessions.pop(session_id)
        return None
    return session["uid"]

class LoginRequest(BaseModel):
    image_data:str

@app.post("/api/login")
async def login(request:LoginRequest):
    if not encodings_cache:
        return JSONResponse({"success": False, "message": "No images in database"}, status_code=400)
    matched_u_id = find_closest_match(request.image_data, encodings_cache)
    if not matched_u_id:
        return JSONResponse({"success": False, "message": "who is this face, idk"}, status_code=401)
    
    conn=access_sql_database()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE uid=%s",(matched_u_id,))
            user=cursor.fetchone()
        if not user:
            return JSONResponse({"sucesss!":False,"message":"This user ain't in my database"},status_code=401)
        with conn.cursor() as cursor:
            cursor.execute("UPDATE users SET is_online=TRUE WHERE uid=%s",(matched_u_id,))
        conn.commit()
    finally:
        conn.close()

    session_id=secrets.token_urlsafe(32)
    sessions[session_id]={
        "uid":matched_u_id,
        "expires":datetime.utcnow()+timedelta(hours=1)
    }

    response=JSONResponse({"sucesss!":True,"uid":matched_u_id,"name":user["name"]})
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        secure=False,
        samesite="Lax",
        max_age=3600 
    )
    return response

@app.get("/api/leaderboard")
async def leaderboard():
    conn = access_sql_database()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT uid, name, elo_rating FROM users ORDER BY elo_rating DESC")
            result = cursor.fetchall()
    finally:
        conn.close()
    return result

@app.post("/api/logout")
async def logout(request: Request):
    session_id=request.cookies.get("session_id")
    if not session_id or session_id not in sessions:
        return JSONResponse({"message":"nOPES not logged in"},status_code=401)
    session=sessions.pop(session_id)
    uid=session["uid"]
    conn=access_sql_database()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE users SET is_online=FALSE WHERE uid=%s",(uid,))
        conn.commit()
    finally:
        conn.close()
    response=JSONResponse({"message":"hawww logged out homie"})
    response.delete_cookie("session_id")
    return response

@app.get("/api/me")
async def me(request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in sessions:
        return JSONResponse({"message": "Not logged in"}, status_code=401)
    session = sessions[session_id]
    if session["expires"] < datetime.utcnow():
        sessions.pop(session_id)
        return JSONResponse({"message": "Session expired"}, status_code=401)
    uid = session["uid"]
    conn = access_sql_database()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT name FROM users WHERE uid = %s", (uid,))
            user = cursor.fetchone()
    finally:
        conn.close()
    return {"uid": uid, "name": user["name"]}

import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.get("/lobby")
async def lobby(request: Request):
    uid = current_user(request)
    if not uid:
        return JSONResponse({"message": "Not logged in"}, status_code=401)
    with open(os.path.join(BASE_DIR, "lobby.html"), "r") as f:
        content = f.read().replace("{{ uid }}", str(uid))
    return HTMLResponse(content)

@app.websocket("/ws/{uid}")
async def websocket_endpoint(websocket: WebSocket, uid: str):
    await manager.connect(uid, websocket)

    conn = access_sql_database()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT uid, name, elo_rating FROM users WHERE is_online = TRUE")
            online_users = cursor.fetchall()
    finally:
        conn.close()
        

    await manager.broadcast_lobby({
        "type": "lobby_update",
        "active_users": online_users,
    })

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "challenge":
                target_id = data.get("to")

                if target_id not in manager.active_connections:
                    await manager.send_personal(uid, {
                        "type": "error",
                        "message": "User is not online :("
                    })
                    continue

                if uid in manager.pending_challenges or target_id in manager.pending_challenges.values():
                    await manager.send_personal(uid, {
                        "type": "error",
                        "message": "One of the users is already in a pending challenge"
                    })
                    continue

                already_in_game = any(
                     uid in room["players"] or target_id in room["players"]
                     for room in manager.game_rooms.values()
                     )
                if already_in_game:
                     await manager.send_personal(uid, {
                          "type": "error",
                          "message": "One of the users is already playing another game"
                          })
                     continue

                manager.pending_challenges[uid] = target_id
                challenger_name = f"User {uid}"

                await manager.send_personal(target_id, {
                    "type": "challenge_received",
                    "from": uid,
                    "name": challenger_name
                })

            elif msg_type == "challenge_response":
                challenger_id = str(data.get("from"))
                accepted = data.get("accepted")

                if challenger_id not in manager.pending_challenges:
                    await manager.send_personal(uid, {
                        "type": "error",
                        "message": "No challenge found"
                    })
                    continue

                if manager.pending_challenges.get(challenger_id) != uid:
                    await manager.send_personal(uid, {
                        "type": "error",
                        "message": "Invalid response bud"
                    })
                    continue

                if not accepted:
                    await manager.send_personal(challenger_id, {
                        "type": "challenge_declined",
                        "by": uid
                    })
                    del manager.pending_challenges[challenger_id]
                    continue

                room_id = str(uuid.uuid4())

                room_state = {
                    "players": {
                        challenger_id: "X",
                        uid: "O"
                    },
                    "board": [None] * 9,
                    "turn": challenger_id
                }

                manager.game_rooms[room_id] = room_state
                manager.player_to_room[challenger_id] = room_id
                manager.player_to_room[uid] = room_id

                del manager.pending_challenges[challenger_id]

                await manager.send_personal(challenger_id, {
                    "type": "game_start",
                    "room_id": room_id,
                    "symbol": "X",
                    "board": room_state["board"],
                    "turn": room_state["turn"]
                })

                await manager.send_personal(uid, {
                    "type": "game_start",
                    "room_id": room_id,
                    "symbol": "O",
                    "board": room_state["board"],
                    "turn": room_state["turn"]
                })

            elif msg_type == "move":
                cell = data.get("cell")

                room_id = manager.player_to_room.get(uid)
                if not room_id:
                    await manager.send_personal(uid, {
                        "type": "error",
                        "message": "You are not in a game :("
                    })
                    continue

                room = manager.game_rooms.get(room_id)
                if not room:
                    await manager.send_personal(uid, {
                        "type": "error",
                        "message": "Game room no longer exists :("
                    })
                    continue

                board = room["board"]
                players = room["players"]

                if room["turn"] != uid:
                    await manager.send_personal(uid, {
                        "type": "error",
                        "message": "WAIT, not your turn"
                    })
                    continue

                if cell is None or not (0 <= cell <= 8):
                    await manager.send_personal(uid, {
                        "type": "error",
                        "message": "Not this cell"
                    })
                    continue

                if board[cell] is not None:
                    await manager.send_personal(uid, {
                        "type": "error",
                        "message": "ITS ALREADY OCCUPIED"
                    })
                    continue

                symbol = players[uid]
                board[cell] = symbol

                winning_combos = [
                    (0,1,2), (3,4,5), (6,7,8),
                    (0,3,6), (1,4,7), (2,5,8),
                    (0,4,8), (2,4,6)
                ]

                winner_uid = None
                for a, b, c in winning_combos:
                    if board[a] and board[a] == board[b] == board[c]:
                        for pid, sym in players.items():
                            if sym == board[a]:
                                winner_uid = pid
                                break
                        break

                is_draw = winner_uid is None and all(c is not None for c in board)

                if winner_uid is None and not is_draw:
                    next_player = [p for p in players if p != uid][0]
                    room["turn"] = next_player

                    for pid in players:
                        await manager.send_personal(pid, {
                            "type": "game_update",
                            "board": board,
                            "turn": room["turn"]
                        })
                    continue

                result = "draw" if is_draw else winner_uid

                for pid in players:
                    await manager.send_personal(pid, {
                        "type": "game_over",
                        "board": board,
                        "winner": result
                    })

                for pid in players:
                    manager.player_to_room.pop(pid, None)
                manager.game_rooms.pop(room_id, None)
                print(f"Game over! Result: {result}, Players: {list(players.keys())}")

                conn = access_sql_database()
                try:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT uid, elo_rating FROM users WHERE uid IN (%s, %s)", 
                                       (list(players.keys())[0], list(players.keys())[1]))
                        ratings = {row["uid"]: row["elo_rating"] for row in cursor.fetchall()}
                    p1, p2 = list(players.keys())
                    r1, r2 = ratings[p1], ratings[p2]
                    if result == "draw":
                        s1, s2 = 0.5, 0.5
                    elif result == p1:
                        s1, s2 = 1.0, 0.0
                    else:
                        s1, s2 = 0.0, 1.0
                    
                    k = 32
                    e1 = 1 / (1 + 10 ** ((r2 - r1) / 400))
                    e2 = 1 / (1 + 10 ** ((r1 - r2) / 400))
                    new_r1 = round(r1 + k * (s1 - e1))
                    new_r2 = round(r2 + k * (s2 - e2))
                    with conn.cursor() as cursor:
                        cursor.execute("UPDATE users SET elo_rating = %s WHERE uid = %s", (new_r1, p1))
                        cursor.execute("UPDATE users SET elo_rating = %s WHERE uid = %s", (new_r2, p2))
                    conn.commit()
                finally:
                    conn.close()

            else:
                await manager.send_personal(uid, {
                    "type": "error",
                    "message": "Unknown message type"
                })

    except WebSocketDisconnect:
        manager.disconnect(uid)
        conn = access_sql_database()
        try:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE users SET is_online = FALSE WHERE uid = %s", (uid,))
            conn.commit()
        finally:
            conn.close()
        conn = access_sql_database()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT uid, name, elo_rating FROM users WHERE is_online = TRUE")
                online_users = cursor.fetchall()
        finally:
            conn.close()
        await manager.broadcast_lobby({
            "type": "lobby_update",
            "active_users": online_users,
        })

app.mount("/", StaticFiles(directory="static", html=True), name="static")