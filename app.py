import os
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_cors import CORS
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor  # ← CETTE LIGNE
from dotenv import load_dotenv
import hashlib

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'MediLogic_Secret_2026')
CORS(app)

DATABASE_URL = os.getenv('DATABASE_URL')

def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def get_annee_courante():
    return datetime.now().year

# ==================== PAGES ====================
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/inscription')
def inscription_page():
    return render_template('inscription.html')

@app.route('/membres')
def membres_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('membres.html')

@app.route('/cotisations')
def cotisations_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('cotisations.html')

@app.route('/caisse')
def caisse_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('caisse.html')

@app.route('/historique')
def historique_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('historique.html')

# ==================== API AUTHENTIFICATION ====================
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    telephone = data['telephone']
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM membres WHERE telephone LIKE %s", (f'%{telephone}%',))
    membre = cur.fetchone()
    cur.close()
    conn.close()
    
    if membre:
        session['user_id'] = membre['id']
        session['user_nom'] = membre['nom']
        session['user_role'] = membre.get('role', 'membre')
        return jsonify({'success': True, 'role': session['user_role'], 'nom': membre['nom']})
    else:
        return jsonify({'success': False, 'message': 'Numéro non trouvé'})

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/session', methods=['GET'])
def get_session():
    if 'user_id' in session:
        return jsonify({
            'logged_in': True,
            'nom': session.get('user_nom'),
            'role': session.get('user_role')
        })
    return jsonify({'logged_in': False})

# ==================== API MEMBRES (avec permissions) ====================
@app.route('/api/membres', methods=['GET'])
def get_membres():
    conn = get_db()
    cur = conn.cursor()
    
    # Les membres voient uniquement les membres actifs (pas les admins cachés)
    if session.get('user_role') == 'membre':
        cur.execute("SELECT id, nom, telephone, statut, montant_mensuel, statut_cotisation FROM membres WHERE role != 'admin' ORDER BY id DESC")
    else:
        cur.execute("SELECT * FROM membres ORDER BY id DESC")
    
    membres = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(membres)

@app.route('/api/membres', methods=['POST'])
def add_membre():
    # Seul l'admin peut ajouter (ou via formulaire public)
    if session.get('user_role') != 'admin':
        # Vérifier si c'est une auto-inscription (pas de session)
        if not session:
            return inscrire_membre_public(request.json)
        return jsonify({'success': False, 'message': 'Permission refusée'}), 403
    
    annee = datetime.now().year
    data = request.json
    montant = 1000 if data['statut'] == 'travailleur' else 500
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO membres (nom, telephone, statut, montant_mensuel, role)
        VALUES (%s, %s, %s, %s, 'membre') RETURNING id
    """, (data['nom'], data['telephone'], data['statut'], montant))
    membre = cur.fetchone()
    membre_id = membre['id']
    
    # Ajouter le nouveau membre dans fete_cotisation pour l'année en cours
    cur.execute("""
        INSERT INTO fete_cotisation (id_membre, annee, montant_total_du, montant_paye, montant_restant, statut)
        VALUES (%s, %s, 5000, 0, 5000, 'impayé')
        ON CONFLICT (id_membre, annee) DO NOTHING
    """, (membre_id, annee))
    
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True, 'message': f'Membre {data["nom"]} ajouté'})

def inscrire_membre_public(data):
    """Inscription publique sans authentification"""
    annee = datetime.now().year
    montant = 1000 if data['statut'] == 'travailleur' else 500
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO membres (nom, telephone, statut, montant_mensuel, role, statut_cotisation)
        VALUES (%s, %s, %s, %s, 'membre', 'En retard') RETURNING id
    """, (data['nom'], data['telephone'], data['statut'], montant))
    membre = cur.fetchone()
    membre_id = membre['id']
    
    # Ajouter le nouveau membre dans fete_cotisation pour l'année en cours
    cur.execute("""
        INSERT INTO fete_cotisation (id_membre, annee, montant_total_du, montant_paye, montant_restant, statut)
        VALUES (%s, %s, 5000, 0, 5000, 'impayé')
        ON CONFLICT (id_membre, annee) DO NOTHING
    """, (membre_id, annee))
    
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True, 'message': f'Membre {data["nom"]} inscrit'})

@app.route('/api/membres/<int:id>', methods=['DELETE'])
def delete_membre(id):
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': 'Permission refusée'}), 403
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # Supprimer dans l'ordre pour éviter les erreurs de clé étrangère
        cur.execute("DELETE FROM fete_cotisation WHERE id_membre = %s", (id,))
        cur.execute("DELETE FROM cotisations WHERE id_membre = %s", (id,))
        cur.execute("DELETE FROM caisse WHERE source = %s", (str(id),))
        cur.execute("DELETE FROM fete_caisse WHERE id_membre = %s", (id,))
        cur.execute("DELETE FROM membres WHERE id = %s", (id,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        cur.close()
        conn.close()

# ==================== API COTISATIONS ====================
@app.route('/api/cotisations', methods=['POST'])
def add_cotisation():
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': 'Seul l\'admin peut enregistrer des paiements'}), 403
    
    data = request.json
    
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT * FROM cotisations 
        WHERE id_membre = %s AND mois = %s AND annee = %s
    """, (data['id_membre'], data['mois'], data['annee']))
    if cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({'success': False, 'message': 'Déjà payé ce mois'})
    
    cur.execute("""
        INSERT INTO cotisations (id_membre, mois, annee, montant, enregistre_par)
        VALUES (%s, %s, %s, %s, %s)
    """, (data['id_membre'], data['mois'], data['annee'], data['montant'], data['enregistre_par']))
    
    cur.execute("UPDATE membres SET statut_cotisation = 'À jour' WHERE id = %s", (data['id_membre'],))
    
    cur.execute("SELECT COALESCE(solde_apres, 0) FROM caisse ORDER BY id DESC LIMIT 1")
    solde = cur.fetchone()
    solde_actuel = solde['coalesce'] if solde else 0
    nouveau_solde = solde_actuel + data['montant']
    
    cur.execute("""
        INSERT INTO caisse (type, montant, motif, source, solde_apres, effectue_par)
        VALUES ('entree', %s, %s, %s, %s, %s)
    """, (data['montant'], f"Cotisation {data['mois']} {data['annee']}", str(data['id_membre']), nouveau_solde, data['enregistre_par']))
    
    conn.commit()
    cur.close()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Paiement enregistré'})

@app.route('/api/cotisations/historique', methods=['GET'])
def get_historique():
    conn = get_db()
    cur = conn.cursor()
    
    if session.get('user_role') == 'membre':
        cur.execute("""
            SELECT c.*, m.nom as membre_nom 
            FROM cotisations c
            JOIN membres m ON c.id_membre = m.id
            WHERE c.id_membre = %s
            ORDER BY c.date_paiement DESC LIMIT 50
        """, (session['user_id'],))
    else:
        cur.execute("""
            SELECT c.*, m.nom as membre_nom 
            FROM cotisations c
            JOIN membres m ON c.id_membre = m.id
            ORDER BY c.date_paiement DESC LIMIT 100
        """)
    
    historique = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(historique)

# ==================== API CAISSE ====================
@app.route('/api/caisse/solde', methods=['GET'])
def get_solde():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(solde_apres, 0) as solde FROM caisse ORDER BY id DESC LIMIT 1")
    solde = cur.fetchone()
    cur.close()
    conn.close()
    
    # Les membres voient un solde masqué
    if session.get('user_role') == 'membre':
        return jsonify({'solde': '🔒 Masqué', 'masque': True})
    return jsonify({'solde': solde['solde'] if solde else 0, 'masque': False})

@app.route('/api/caisse/operations', methods=['GET'])
def get_operations():
    conn = get_db()
    cur = conn.cursor()
    
    if session.get('user_role') == 'membre':
        cur.execute("SELECT date_operation, type, montant, motif FROM caisse WHERE type = 'entree' ORDER BY date_operation DESC LIMIT 20")
    else:
        cur.execute("SELECT * FROM caisse ORDER BY date_operation DESC LIMIT 50")
    
    ops = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(ops)

@app.route('/api/caisse/sortie', methods=['POST'])
def add_sortie():
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': 'Seul l\'admin peut décaisser'}), 403
    
    data = request.json
    
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT COALESCE(solde_apres, 0) as solde FROM caisse ORDER BY id DESC LIMIT 1")
    solde = cur.fetchone()
    solde_actuel = solde['solde'] if solde else 0
    
    if solde_actuel < data['montant']:
        cur.close()
        conn.close()
        return jsonify({'success': False, 'message': 'Solde insuffisant'})
    
    nouveau_solde = solde_actuel - data['montant']
    cur.execute("""
        INSERT INTO caisse (type, montant, motif, source, solde_apres, effectue_par, valide_par)
        VALUES ('sortie', %s, %s, %s, %s, %s, %s)
    """, (data['montant'], data['motif'], 'Décaissement', nouveau_solde, session['user_nom'], session['user_nom']))
    
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True, 'message': f'Décaissement de {data["montant"]} FCFA effectué'})

# ==================== API STATS ====================
@app.route('/api/stats', methods=['GET'])
def get_stats():
    conn = get_db()
    cur = conn.cursor()
    
    if session.get('user_role') == 'membre':
        # Stats limitées pour les membres
        cur.execute("SELECT COUNT(*) as total FROM membres")
        total = cur.fetchone()['total']
        
        cur.execute("SELECT COUNT(*) FROM membres WHERE statut_cotisation = 'À jour'")
        ajour = cur.fetchone()['count']
        
        cur.execute("SELECT COUNT(*) FROM cotisations WHERE id_membre = %s", (session['user_id'],))
        mes_paiements = cur.fetchone()['count']
        
        cur.close()
        conn.close()
        
        return jsonify({
            'total_membres': total,
            'mes_paiements': mes_paiements,
            'mon_statut': 'À jour' if ajour > 0 else 'En retard',
            'taux_recouvrement': round((ajour / total * 100), 1) if total > 0 else 0
        })
    else:
        cur.execute('SELECT COUNT(*) as total FROM membres')
        total = cur.fetchone()['total']
        
        cur.execute("SELECT COUNT(*) FROM membres WHERE statut = 'travailleur'")
        travailleurs = cur.fetchone()['count']
        
        cur.execute("SELECT COUNT(*) FROM membres WHERE statut_cotisation = 'À jour'")
        ajour = cur.fetchone()['count']
        
        cur.execute("SELECT COALESCE(solde_apres, 0) FROM caisse ORDER BY id DESC LIMIT 1")
        solde = cur.fetchone()
        
        cur.close()
        conn.close()
        
        taux = round((ajour / total * 100), 1) if total > 0 else 0
        
        return jsonify({
            'total_membres': total,
            'travailleurs': travailleurs,
            'non_travailleurs': total - travailleurs,
            'solde_caisse': solde['coalesce'] if solde else 0,
            'taux_recouvrement': taux,
            'a_jour': ajour,
            'en_retard': total - ajour
        })

@app.route('/api/membres/retard', methods=['GET'])
def get_retard():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, nom, telephone, montant_mensuel, statut_cotisation FROM membres")
    membres = cur.fetchall()
    cur.close()
    conn.close()
    
    resultat = []
    for m in membres:
        retard = calculer_retards_membre(m['id'])
        if retard['nombre_mois'] > 0:
            resultat.append({
                'id': m['id'],
                'nom': m['nom'],
                'telephone': m['telephone'],
                'montant_mensuel': m['montant_mensuel'],
                'mois_retard': retard['nombre_mois'],
                'dette_totale': retard['dette_totale']
            })
    
    return jsonify(resultat)

@app.route('/api/admin/login', methods=['POST'])
def api_admin_login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    hash_mdp = hashlib.sha256(password.encode()).hexdigest()
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM admin WHERE username = %s AND password_hash = %s", (username, hash_mdp))
    admin = cur.fetchone()
    cur.close()
    conn.close()
    
    if admin:
        session['user_id'] = 0  # ID spécial pour admin
        session['user_nom'] = 'Administrateur'
        session['user_role'] = 'admin'
        return jsonify({'success': True})
    else:
        return jsonify({'success': False})

@app.route('/api/membre/login', methods=['POST'])
def api_membre_login():
    data = request.json
    telephone = data.get('telephone')
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, nom, role FROM membres WHERE telephone LIKE %s", (f'%{telephone}%',))
    membre = cur.fetchone()
    cur.close()
    conn.close()
    
    if membre:
        session['user_id'] = membre['id']
        session['user_nom'] = membre['nom']
        session['user_role'] = membre.get('role', 'membre')
        return jsonify({'success': True, 'nom': membre['nom']})
    else:
        return jsonify({'success': False, 'message': 'Numéro non trouvé'})

# ==================== FONCTION CALCUL RETARDS ====================
def calculer_retards_membre(id_membre):
    """Calcule les mois de retard pour un membre"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT id, nom, montant_mensuel FROM membres WHERE id = %s", (id_membre,))
    membre = cur.fetchone()
    
    if not membre:
        return {'nombre_mois': 0, 'dette_totale': 0}
    
    # Récupérer les mois déjà payés (en utilisant la colonne 'mois')
    cur.execute("""
        SELECT DISTINCT annee, mois
        FROM cotisations 
        WHERE id_membre = %s
    """, (id_membre,))
    
    mois_payes = []
    mois_numeros = {
        'Janvier': 1, 'Février': 2, 'Mars': 3, 'Avril': 4,
        'Mai': 5, 'Juin': 6, 'Juillet': 7, 'Août': 8,
        'Septembre': 9, 'Octobre': 10, 'Novembre': 11, 'Décembre': 12
    }
    
    for row in cur.fetchall():
        mois_num = mois_numeros.get(row['mois'], 0)
        if mois_num > 0:
            mois_payes.append(f"{row['annee']}-{mois_num:02d}")
    
    cur.close()
    conn.close()
    
    aujourd_hui = datetime.now()
    annee_courante = aujourd_hui.year
    mois_courant = aujourd_hui.month
    jour_courant = aujourd_hui.day
    
    mois_impayes = []
    
    for mois in range(1, mois_courant + 1):
        mois_annee = f"{annee_courante}-{mois:02d}"
        
        if mois_annee in mois_payes:
            continue
        
        if mois == mois_courant:
            if jour_courant > 5:
                mois_impayes.append({'mois_annee': mois_annee, 'montant': membre['montant_mensuel']})
        else:
            mois_impayes.append({'mois_annee': mois_annee, 'montant': membre['montant_mensuel']})
    
    dette_totale = sum(m['montant'] for m in mois_impayes)
    nombre_mois = len(mois_impayes)
    
    return {'nombre_mois': nombre_mois, 'dette_totale': dette_totale}

# ==================== FÊTE DE FIN D'ANNÉE ====================

@app.route('/fete')
def fete_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('fete.html')

@app.route('/api/fete/stats', methods=['GET'])
def api_fete_stats():
    annee = datetime.now().year
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT COUNT(*) as total FROM membres")
    total_membres = cur.fetchone()['total']
    objectif_total = total_membres * 5000
    
    cur.execute("SELECT COALESCE(SUM(montant_paye), 0) as total FROM fete_cotisation WHERE annee = %s", (annee,))
    total_collecte = cur.fetchone()['total']
    
    cur.execute("SELECT COUNT(*) as count FROM fete_cotisation WHERE annee = %s AND montant_paye > 0", (annee,))
    participants = cur.fetchone()['count']
    taux = round((participants / total_membres * 100), 1) if total_membres > 0 else 0
    
    cur.execute("SELECT COALESCE(solde, 0) as solde FROM fete_solde ORDER BY id DESC LIMIT 1")
    solde = cur.fetchone()
    
    cur.close()
    conn.close()
    
    return jsonify({
        'objectif_total': objectif_total,
        'total_collecte': total_collecte,
        'taux_participation': taux,
        'solde_caisse': solde['solde'] if solde else 0,
        'annee': annee
    })
@app.route('/api/fete/membres', methods=['GET'])
def api_fete_membres():
    annee = datetime.now().year
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT m.id, m.nom, m.telephone, 
               COALESCE(f.montant_paye, 0) as montant_paye,
               COALESCE(f.montant_restant, 5000) as montant_restant,
               COALESCE(f.statut, 'impayé') as statut
        FROM membres m
        LEFT JOIN fete_cotisation f ON m.id = f.id_membre AND f.annee = %s
        ORDER BY m.nom
    """, (annee,))
    membres = cur.fetchall()
    cur.close()
    conn.close()
    
    return jsonify(membres)

@app.route('/api/fete/payer', methods=['POST'])
def api_fete_payer():
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': 'Seul l\'admin peut enregistrer les paiements'})
    
    annee = datetime.now().year
    data = request.json
    id_membre = data['id_membre']
    montant = data['montant']
    
    if not id_membre or not montant or montant <= 0:
        return jsonify({'success': False, 'message': 'Montant invalide'})
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        cur.execute("SELECT * FROM fete_cotisation WHERE id_membre = %s AND annee = %s", (id_membre, annee))
        existing = cur.fetchone()
        
        if existing:
            nouveau_paye = existing['montant_paye'] + montant
            nouveau_reste = 5000 - nouveau_paye
            nouveau_statut = 'payé' if nouveau_paye >= 5000 else ('partiel' if nouveau_paye > 0 else 'impayé')
            
            cur.execute("""
                UPDATE fete_cotisation 
                SET montant_paye = %s, montant_restant = %s, statut = %s, date_dernier_paiement = NOW()
                WHERE id_membre = %s AND annee = %s
            """, (nouveau_paye, nouveau_reste, nouveau_statut, id_membre, annee))
        else:
            nouveau_reste = 5000 - montant
            nouveau_statut = 'partiel' if montant < 5000 else 'payé'
            cur.execute("""
                INSERT INTO fete_cotisation (id_membre, annee, montant_total_du, montant_paye, montant_restant, statut, date_dernier_paiement)
                VALUES (%s, %s, 5000, %s, %s, %s, NOW())
            """, (id_membre, annee, montant, nouveau_reste, nouveau_statut))
        
        cur.execute("SELECT COALESCE(SUM(montant_paye), 0) as total FROM fete_cotisation WHERE annee = %s", (annee,))
        total_collecte = cur.fetchone()['total']
        
        cur.execute("DELETE FROM fete_solde")
        cur.execute("INSERT INTO fete_solde (solde) VALUES (%s)", (total_collecte,))
        
        motif = f"Cotisation fete de fin d annee {annee}"
        cur.execute("""
            INSERT INTO fete_caisse (type, montant, motif, source, solde_apres, effectue_par, id_membre)
            VALUES ('entree', %s, %s, %s, %s, %s, %s)
        """, (montant, motif, str(id_membre), total_collecte, session.get('user_nom', 'admin'), id_membre))
        
        conn.commit()
        
        cur.execute("SELECT montant_paye, montant_restant, statut FROM fete_cotisation WHERE id_membre = %s AND annee = %s", (id_membre, annee))
        result = cur.fetchone()
        
        return jsonify({
            'success': True, 
            'message': f'{montant} FCFA enregistre',
            'montant_paye': result['montant_paye'],
            'montant_restant': result['montant_restant'],
            'statut': result['statut']
        })
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        cur.close()
        conn.close()

@app.route('/api/fete/rappel', methods=['POST'])
def api_fete_rappel():
    annee = datetime.now().year
    data = request.json
    id_membre = data.get('id_membre')
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT m.nom, m.telephone, COALESCE(f.montant_paye, 0) as paye, COALESCE(f.montant_restant, 5000) as reste
        FROM membres m
        LEFT JOIN fete_cotisation f ON m.id = f.id_membre AND f.annee = %s
        WHERE m.id = %s
    """, (annee, id_membre))
    membre = cur.fetchone()
    cur.close()
    conn.close()
    
    if membre:
        telephone = membre['telephone'].replace(' ', '').replace('+', '')
        message = f"Bonjour {membre['nom']}, cotisation Fete de fin d annee {annee}: {membre['paye']} FCFA deja paye, reste {membre['reste']} FCFA. Date limite: 20 decembre. Merci!"
        url = f"https://wa.me/{telephone}?text={message}"
        return jsonify({'success': True, 'url': url})
    
    return jsonify({'success': False, 'message': 'Membre non trouve'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)