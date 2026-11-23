from __future__ import annotations
import sqlite3
import uuid
from pathlib import Path

class SavedPlayerStore:
    def __init__(self, db_path):
        self.db_path=str(db_path)
        if self.db_path != ":memory:": Path(self.db_path).parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.db_path) as c:
            c.execute("""CREATE TABLE IF NOT EXISTS saved_players(player_id TEXT PRIMARY KEY, display_name TEXT NOT NULL COLLATE NOCASE, gender TEXT NOT NULL CHECK(gender IN ('male','female')), active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    def list(self, active_only=False):
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            sql="SELECT player_id,display_name,gender,active FROM saved_players"
            if active_only: sql+=" WHERE active=1"
            sql+=" ORDER BY active DESC, display_name COLLATE NOCASE"
            return [dict(x) for x in c.execute(sql)]
    def add(self,name,gender):
        name=name.strip()
        if not name: raise ValueError("Player name cannot be empty")
        with sqlite3.connect(self.db_path) as c:
            if c.execute("SELECT 1 FROM saved_players WHERE display_name=? COLLATE NOCASE",(name,)).fetchone(): raise ValueError("A saved player with that name already exists")
            pid=uuid.uuid4().hex
            c.execute("INSERT INTO saved_players(player_id,display_name,gender) VALUES(?,?,?)",(pid,name,gender))
            return pid
    def update(self,pid,name,gender,active):
        name=name.strip()
        if not name: raise ValueError("Player name cannot be empty")
        with sqlite3.connect(self.db_path) as c:
            if c.execute("SELECT 1 FROM saved_players WHERE display_name=? COLLATE NOCASE AND player_id<>?",(name,pid)).fetchone(): raise ValueError("A saved player with that name already exists")
            cur=c.execute("UPDATE saved_players SET display_name=?,gender=?,active=? WHERE player_id=?",(name,gender,int(active),pid))
            return cur.rowcount
    def delete(self,pid):
        with sqlite3.connect(self.db_path) as c:
            return c.execute("DELETE FROM saved_players WHERE player_id=?",(pid,)).rowcount
