CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  body TEXT,
  photo_key TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
