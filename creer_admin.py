import psycopg2
import os
import hashlib
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

# Créer la table admin si elle n'existe pas
cur.execute("""
    CREATE TABLE IF NOT EXISTS admin (
        id SERIAL PRIMARY KEY,
        username VARCHAR(50) UNIQUE,
        password_hash VARCHAR(200)
    )
""")

# Mot de passe admin@123
mot_de_passe = "admin@123"
hash_mdp = hashlib.sha256(mot_de_passe.encode()).hexdigest()

cur.execute("""
    INSERT INTO admin (username, password_hash) 
    VALUES ('admin', %s)
    ON CONFLICT (username) DO UPDATE SET password_hash = %s
""", (hash_mdp, hash_mdp))

conn.commit()
cur.close()
conn.close()

print("✅ Admin créé avec succès !")
print("📝 Identifiants :")
print("   Nom d'utilisateur: admin")
print("   Mot de passe: admin@123")