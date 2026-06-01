import sqlite3
conn = sqlite3.connect('data/jobs.db')
conn.execute("UPDATE jobs SET status='transcribed', error_message=NULL WHERE id=1")
conn.commit()
conn.close()
print('OK')
