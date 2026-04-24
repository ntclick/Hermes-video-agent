import sqlite3
c = sqlite3.connect('data/content_bridge.db')
try:
    c.execute('ALTER TABLE jobs ADD COLUMN user_keys_json TEXT')
    c.commit()
    print('Column added OK')
except Exception as e:
    print(f'Already exists or error: {e}')
