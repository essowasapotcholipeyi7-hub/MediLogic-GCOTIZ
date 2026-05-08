import os
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_cors import CORS
from datetime import datetime
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
import hashlib

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'MediLogic_Secret_2026')
CORS(app)

DATABASE_URL = os.getenv('DATABASE_URL')

def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

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
    
    data = request.json
    montant = 1000 if data['statut'] == 'travailleur' else 500
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO membres (nom, telephone, statut, montant_mensuel, role)
        VALUES (%s, %s, %s, %s, 'membre') RETURNING *
    """, (data['nom'], data['telephone'], data['statut'], montant))
    membre = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True, 'membre': membre})

def inscrire_membre_public(data):
    """Inscription publique sans authentification"""
    montant = 1000 if data['statut'] == 'travailleur' else 500
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO membres (nom, telephone, statut, montant_mensuel, role, statut_cotisation)
        VALUES (%s, %s, %s, %s, 'membre', 'En retard') RETURNING *
    """, (data['nom'], data['telephone'], data['statut'], montant))
    membre = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True, 'membre': membre})

@app.route('/api/membres/<int:id>', methods=['DELETE'])
def delete_membre(id):
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': 'Permission refusée'}), 403
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM membres WHERE id = %s', (id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True})

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
    
    if session.get('user_role') == 'membre':
        # Un membre voit juste "toi-même"
        cur.execute("SELECT id, nom, telephone, montant_mensuel FROM membres WHERE id = %s AND statut_cotisation = 'En retard'", (session['user_id'],))
    else:
        cur.execute("SELECT id, nom, telephone, montant_mensuel FROM membres WHERE statut_cotisation = 'En retard'")
    
    retard = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(retard)

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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)