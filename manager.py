from fastapi import WebSocket
from typing import Dict, Set
import asyncio

class ConnectionManager:
    def __init__(self):
        # Active WebSocket connections: user_id -> WebSocket
        self.active_connections: Dict[int, WebSocket] = {}

        # Pending challenges: challenger_id -> challenged_id
        self.pending_challenges: Dict[int, int] = {}

        # Active game rooms: room_id -> room_state
        self.game_rooms: Dict[str, dict] = {}

        # Player to room mapping: user_id -> room_id
        self.player_to_room: Dict[int, str] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        # TODO: Update user status in MySQL (e.g., set online = True)

    def disconnect(self, user_id: int):
        # --- Case 1: user is in an active game ---
        room_id = self.player_to_room.get(user_id)

        if room_id:
            room = self.game_rooms.get(room_id)

            if room:
                players = room["players"]

                # Find the opponent
                opponent_id = next((pid for pid in players if pid != user_id), None)

                # Notify opponent of forfeit win
                if opponent_id and opponent_id in self.active_connections:
                    asyncio.create_task(
                        self.send_personal(opponent_id, {
                            "type": "game_over",
                            "board": room["board"],
                            "winner": opponent_id,
                            "reason": "forfeit"
                        })
                    )

                # Mark room as finished
                room["finished"] = True

                if opponent_id:
                    try:
                        import pymysql, pymysql.cursors, os
                        conn = pymysql.connect(
                            host=os.getenv("MYSQL_HOST", "localhost"),
                            user=os.getenv("MYSQL_USER", "root"),
                            password=os.getenv("MYSQL_PASSWORD", ""),
                            database=os.getenv("MYSQL_DB", "arena_db"),
                            cursorclass=pymysql.cursors.DictCursor
                        )
                        with conn.cursor() as cursor:
                            cursor.execute("SELECT uid, elo_rating FROM users WHERE uid IN (%s, %s)", (opponent_id, user_id))
                            ratings = {row["uid"]: row["elo_rating"] for row in cursor.fetchall()}
                        r_winner = ratings[opponent_id]
                        r_loser = ratings[user_id]
                        k = 32
                        e_winner = 1 / (1 + 10 ** ((r_loser - r_winner) / 400))
                        e_loser = 1 / (1 + 10 ** ((r_winner - r_loser) / 400))
                        new_r_winner = round(r_winner + k * (1.0 - e_winner))
                        new_r_loser = round(r_loser + k * (0.0 - e_loser))
                        with conn.cursor() as cursor:
                            cursor.execute("UPDATE users SET elo_rating = %s WHERE uid = %s", (new_r_winner, opponent_id))
                            cursor.execute("UPDATE users SET elo_rating = %s WHERE uid = %s", (new_r_loser, user_id))
                        conn.commit()
                        conn.close()
                    except Exception as e:
                        print(f"Elo update on forfeit failed: {e}")

            # Clean up player -> room mappings
            for pid in list(self.player_to_room.keys()):
                if self.player_to_room.get(pid) == room_id:
                    self.player_to_room.pop(pid, None)

            # Remove room
            self.game_rooms.pop(room_id, None)

        # --- Case 2: lobby disconnect or general cleanup ---

        # Remove from active connections
        self.active_connections.pop(user_id, None)

        # Clean up pending challenges
        self.pending_challenges = {
            c: t for c, t in self.pending_challenges.items()
            if c != user_id and t != user_id
        }

        # --- MySQL status update ---
        # TODO: set user is_online = False in MySQL

    async def send_personal(self, user_id: int, message: dict):
        websocket = self.active_connections.get(user_id)
        if websocket:
            await websocket.send_json(message)
        else:
            # TODO: Optionally queue message in MySQL for offline delivery
            pass

    async def broadcast_lobby(self, message: dict):
        disconnected_users = []

        for user_id, websocket in self.active_connections.items():
            try:
                await websocket.send_json(message)
            except Exception:
                disconnected_users.append(user_id)

        for user_id in disconnected_users:
            self.disconnect(user_id)