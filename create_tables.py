import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

# Création des tables dans le bon ordre
cur.execute("""
-- Table des paramètres (en premier)
CREATE TABLE IF NOT EXISTS parametres (
    cle VARCHAR(50) PRIMARY KEY,
    valeur TEXT,
    date_modification TIMESTAMP DEFAULT NOW()
);

-- Table des membres
CREATE TABLE IF NOT EXISTS membres (
    id SERIAL PRIMARY KEY,
    nom VARCHAR(100) NOT NULL,
    telephone VARCHAR(20) NOT NULL,
    statut VARCHAR(20) CHECK (statut IN ('travailleur', 'non_travailleur')),
    montant_mensuel INTEGER,
    date_inscription TIMESTAMP DEFAULT NOW(),
    statut_cotisation VARCHAR(20) DEFAULT 'En retard'
);

-- Table des cotisations
CREATE TABLE IF NOT EXISTS cotisations (
    id SERIAL PRIMARY KEY,
    id_membre INTEGER REFERENCES membres(id) ON DELETE CASCADE,
    mois VARCHAR(20),
    annee INTEGER,
    montant INTEGER,
    date_paiement TIMESTAMP DEFAULT NOW(),
    enregistre_par VARCHAR(100)
);

-- Table de la caisse
CREATE TABLE IF NOT EXISTS caisse (
    id SERIAL PRIMARY KEY,
    date_operation TIMESTAMP DEFAULT NOW(),
    type VARCHAR(10) CHECK (type IN ('entree', 'sortie')),
    montant INTEGER,
    motif TEXT,
    source VARCHAR(100),
    solde_apres INTEGER,
    effectue_par VARCHAR(100),
    valide_par VARCHAR(100)
);

-- Insertion des paramètres par défaut (après création de la table)
INSERT INTO parametres (cle, valeur) VALUES 
    ('tarif_travailleur', '1000'),
    ('tarif_non_travailleur', '500'),
    ('annee_courante', '2026'),
    ('mois_courant', '5')
ON CONFLICT (cle) DO NOTHING;

-- Index pour les performances
CREATE INDEX IF NOT EXISTS idx_cotisations_membre ON cotisations(id_membre);
CREATE INDEX IF NOT EXISTS idx_cotisations_date ON cotisations(date_paiement);
CREATE INDEX IF NOT EXISTS idx_caisse_date ON caisse(date_operation);
""")

conn.commit()
cur.close()
conn.close()

print("✅ Tables créées avec succès sur Neon !")