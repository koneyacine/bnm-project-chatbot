import psycopg2
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from langchain_openai import ChatOpenAI
from datetime import datetime
import uuid
import hashlib
import os

load_dotenv()

conn = psycopg2.connect(
    dbname="ma_base_vector",
    user="postgres",
    password="Yacine-96",
    host="localhost",
    port="5433"
)
cur = conn.cursor()

embeddings = OpenAIEmbeddings()
llm = ChatOpenAI(model="gpt-4o-mini")

# 1. CRÉATION DES TABLES POUR MULTI-USERS AVEC MOT DE PASSE
# Table des utilisateurs avec mot de passe hashé
cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id VARCHAR(100) PRIMARY KEY,
        username VARCHAR(100) UNIQUE,
        email VARCHAR(200) UNIQUE,
        password_hash VARCHAR(200) NOT NULL,
        salt VARCHAR(200) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login TIMESTAMP
    );
""")

# Table d'historique avec user_id
cur.execute("""
    CREATE TABLE IF NOT EXISTS conversation_history (
        id SERIAL PRIMARY KEY,
        session_id VARCHAR(100),
        user_id VARCHAR(100) REFERENCES users(user_id),
        role VARCHAR(10),
        content TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_history_user ON conversation_history(user_id);
    CREATE INDEX IF NOT EXISTS idx_history_session ON conversation_history(session_id);
""")
conn.commit()


# 2. FONCTIONS DE SÉCURITÉ POUR LES MOTS DE PASSE
def hash_password(password, salt=None):
    """Hacher le mot de passe avec un salt"""
    if salt is None:
        # Générer un salt aléatoire
        salt = os.urandom(32).hex()

    # Créer le hash (SHA-256 + salt)
    password_hash = hashlib.sha256((password + salt).encode()).hexdigest()
    return password_hash, salt


def verify_password(password, stored_hash, salt):
    """Vérifier si le mot de passe correspond au hash"""
    password_hash, _ = hash_password(password, salt)
    return password_hash == stored_hash


# 3. FONCTIONS DE GESTION DES UTILISATEURS (AVEC MOT DE PASSE)
def create_user(username, email, password):
    """Créer un nouvel utilisateur avec mot de passe"""
    user_id = str(uuid.uuid4())
    try:
        # Hacher le mot de passe
        password_hash, salt = hash_password(password)

        cur.execute(
            "INSERT INTO users (user_id, username, email, password_hash, salt) VALUES (%s, %s, %s, %s, %s)",
            (user_id, username, email, password_hash, salt)
        )
        conn.commit()
        print(f"✅ Utilisateur créé avec succès: {username}")
        return user_id
    except psycopg2.Error as e:
        conn.rollback()
        if "duplicate key" in str(e):
            if "username" in str(e):
                print(" Ce nom d'utilisateur existe déjà")
            elif "email" in str(e):
                print(" Cet email est déjà utilisé")
        else:
            print(f" Erreur: {e}")
        return None


def authenticate_user(username, password):
    """Authentifier un utilisateur"""
    cur.execute(
        "SELECT user_id, username, email, password_hash, salt FROM users WHERE username = %s",
        (username,)
    )
    user = cur.fetchone()

    if not user:
        return None

    user_id, username, email, stored_hash, salt = user

    # Vérifier le mot de passe
    if verify_password(password, stored_hash, salt):
        # Mettre à jour last_login
        cur.execute(
            "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE user_id = %s",
            (user_id,)
        )
        conn.commit()
        return (user_id, username, email)

    return None


def get_user_history(user_id, limit=10):
    """Récupère l'historique d'un utilisateur spécifique"""
    cur.execute("""
        SELECT role, content, timestamp, session_id
        FROM conversation_history 
        WHERE user_id = %s 
        ORDER BY timestamp DESC 
        LIMIT %s;
    """, (user_id, limit))
    return cur.fetchall()


# 4. FONCTIONS D'HISTORIQUE
def get_session_history(session_id, user_id, limit=5):
    """Retrieve last N conversations for a session"""
    cur.execute("""
        SELECT role, content 
        FROM conversation_history 
        WHERE session_id = %s AND user_id = %s
        ORDER BY timestamp DESC 
        LIMIT %s;
    """, (session_id, user_id, limit))

    history = cur.fetchall()
    return list(reversed(history))


def save_to_history(session_id, user_id, role, content):
    """Save a conversation turn with user_id"""
    cur.execute(
        "INSERT INTO conversation_history (session_id, user_id, role, content) VALUES (%s, %s, %s, %s)",
        (session_id, user_id, role, content)
    )
    conn.commit()


# 5. MENU DE CONNEXION/INSCRIPTION AVEC MOT DE PASSE
print("\n" + "=" * 50)
print(" BIENVENUE DANS NOTRE SYSTÈME RAG ")
print("=" * 50)

while True:
    print("\n1. Se connecter")
    print("2. Créer un compte")
    print("3. Quitter")

    choice = input("\nVotre choix (1-3): ").strip()

    if choice == '3':
        cur.close()
        conn.close()
        print("Au revoir !")
        exit()

    elif choice == '2':
        print("\n--- CRÉATION DE COMPTE ---")
        username = input("Nom d'utilisateur: ").strip()
        email = input("Email: ").strip()
        password = input("Mot de passe: ").strip()
        password_confirm = input("Confirmer le mot de passe: ").strip()

        if not all([username, email, password]):
            print(" Tous les champs sont obligatoires")
            continue

        if password != password_confirm:
            print(" Les mots de passe ne correspondent pas")
            continue

        if len(password) < 6:
            print(" Le mot de passe doit contenir au moins 6 caractères")
            continue

        user_id = create_user(username, email, password)
        if user_id:
            print("✅ Compte créé avec succès ! Vous pouvez maintenant vous connecter.")
        continue

    elif choice == '1':
        print("\n--- CONNEXION ---")
        username = input("Nom d'utilisateur: ").strip()
        password = input("Mot de passe: ").strip()

        user = authenticate_user(username, password)

        if not user:
            print("Oups! Nom d'utilisateur ou mot de passe incorrect. Si vous n'avez pas encore de compte, veuillez vous inscrire.")
            continue

        user_id, username, email = user
        print(f"✅ Connecté en tant que: {username}")
        break

# 6. GESTION DE SESSION
print("\n" + "=" * 50)
print("💬 SESSION DE CHAT")
print("=" * 50)

session_id = input("\nEntrez session ID (ou Enter pour nouvelle session): ").strip()
if not session_id:
    session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"📌 Nouvelle session créée: {session_id}")

# Afficher l'historique récent de l'utilisateur
history = get_user_history(user_id, limit=5)
if history:
    print(f"\n📜 Historique récent de {username}:")
    for role, content, timestamp, sess_id in history:
        # Tronquer le contenu pour l'affichage
        short_content = content[:50] + "..." if len(content) > 50 else content
        print(f"  • [{timestamp.strftime('%d/%m %H:%M')}] {role}: {short_content}")

print(f"\nSession active: {session_id}")
print("Commandes: 'exit' pour quitter, 'new' pour nouvelle session, 'history' pour voir l'historique\n")

# 7. BOUCLE PRINCIPALE DE CHAT
while True:
    question = input("\n Votre question: ").strip()

    if question.lower() == 'exit':
        break
    elif question.lower() == 'new':
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        print(f"📌 Nouvelle session créée: {session_id}")
        continue
    elif question.lower() == 'history':
        history = get_user_history(user_id, limit=10)
        print(f"\n📜 Historique complet de {username}:")
        for role, content, timestamp, sess_id in history:
            short_content = content[:50] + "..." if len(content) > 50 else content
            print(f"  • [{timestamp.strftime('%d/%m %H:%M')}] [{sess_id}] {role}: {short_content}")
        continue
    elif not question:
        continue

    #  DÉTECTION DES SALUTATIONS ET QUESTIONS PERSONNELLES
    question_lower = question.lower().strip()

    # Détection de l'heure pour les salutations appropriées
    current_hour = datetime.now().hour
    if 5 <= current_hour < 18:
        time_greeting = "Bonjour"
    elif 18 <= current_hour < 22:
        time_greeting = "Bonsoir"
    else:
        time_greeting = "Bonsoir (il est tard, mais je suis toujours là)"

    # 1. SALUTATIONS
    greetings = ['salut', 'bonjour', 'bonsoir', 'salam', 'hello', 'hi', 'bon matin', 'bsr', 'bjr', 'coucou', 'hey']
    if any(greeting in question_lower for greeting in greetings):
        # Vérifier si c'est une salutation simple (phrase courte)
        if len(question_lower.split()) <= 4:
            response_content = f"{time_greeting} ! Comment puis-je vous aider aujourd'hui ? "
            print(f"\n Réponse:\n{response_content}")
            save_to_history(session_id, user_id, "user", question)
            save_to_history(session_id, user_id, "assistant", response_content)
            continue

    # 2. REMERCIEMENTS
    thanks = ['merci', 'thank', 'thanks', 'je te remercie', 'je vous remercie', 'mercii', 'merci beaucoup', 'merci bcp',
              'merci bien']
    if any(thank in question_lower for thank in thanks):
        response_content = "Avec plaisir ! C'est un honneur de vous aider. N'hésitez pas si vous avez d'autres questions. 😊"
        print(f"\n Réponse:\n{response_content}")
        save_to_history(session_id, user_id, "user", question)
        save_to_history(session_id, user_id, "assistant", response_content)
        continue

    # 3. QUESTIONS SUR L'IDENTITÉ
    identity_questions = [
        'qui es tu', 'qui êtes vous', 'tu es qui', 'vous êtes qui',
        'presente toi', 'présente toi', 'presentez vous', 'présentez vous',
        'quel est ton nom', 'comment tu t appelle', 'comment tu t appelles',
        'c est quoi toi', 't es quoi', 'que fais tu', 'que faites vous',
        'tu es quoi', 'vous êtes quoi', 'ta fonction', 'votre fonction',
        'qui es-tu', 'presentation', 'présentation', 'peux tu te presenter',
        'peux tu te présenter', 'pourrais tu te presenter', 'who are you'
    ]

    if any(identity in question_lower for identity in identity_questions):
        response_content = """ **Je suis un agent IA conçu par la BNM (Banque Nationale de Mauritanie)** pour assister les clients et répondre à leurs questions.

 **Mes missions :**
- Répondre à vos questions sur les services de la BNM
- Vous guider dans vos démarches bancaires
- Fournir des informations sur les produits financiers
- Vous assister 24h/24 et 7j/7

 **Votre confort compte pour nous !** N'hésitez pas à me poser toutes vos questions, je suis là pour vous aider.

 **Pour toute urgence**, vous pouvez aussi contacter notre service client ou visiter notre agence la plus proche."""
        print(f"\n Réponse:\n{response_content}")
        save_to_history(session_id, user_id, "user", question)
        save_to_history(session_id, user_id, "assistant", response_content)
        continue

    # 4. DÉTECTION DES QUESTIONS SUR L'ÉTAT
    etat_questions = ['comment ça va', 'comment allez vous', 'ça va', 'comment tu vas', 'comment vous allez',
                      'ça roule', 'comment vas tu']
    if any(etat in question_lower for etat in etat_questions):
        response_content = "Je vais très bien, merci ! Et vous, comment allez-vous aujourd'hui ? "
        print(f"\n Réponse:\n{response_content}")
        save_to_history(session_id, user_id, "user", question)
        save_to_history(session_id, user_id, "assistant", response_content)
        continue

    # Embed question
    question_vector = embeddings.embed_query(question)

    # Retrieve top 5 similar chunks
    cur.execute(
        """
        SELECT content, source
        FROM documents
        ORDER BY embedding <-> %s::vector
        LIMIT 5;
        """,
        (question_vector,)
    )

    results = cur.fetchall()

    context = ""
    for content, source in results:
        context += f"[Source: {source}]\n{content}\n\n"

    # Get conversation history
    history = get_session_history(session_id, user_id)

    # Format history for prompt
    history_text = ""
    if history:
        history_text = "Previous conversation:\n"
        for role, content in history:
            history_text += f"{role}: {content}\n"
        history_text += "\n"

    # Extraire le dernier sujet de conversation
    last_subject = ""
    if history:
        # Prendre le dernier message de l'assistant qui pourrait contenir le sujet
        for role, content in reversed(history):
            if role == "assistant":
                # Extraire le premier sujet important (simplifié)
                words = content.split()
                if len(words) > 5:
                    last_subject = " ".join(words[:10]) + "..."  # Début de la réponse
                break

    prompt = f"""You are an assistant that answers ONLY using the provided context about BNM.
If the answer is not in the context, say you don't know.

    IMPORTANT: Use the conversation history to understand context and references.

    Current conversation topic: {last_subject if last_subject else "General BNM inquiries"}

    Recent conversation:
    {history_text if history else "No previous conversation."}

    Relevant documents:
    {context}

    Current question: {question}

    Instructions:
    1. If the question refers to something mentioned before (like "it", "its", "sa", "son", "leur"), look in the conversation history
    2. Only use information from the provided documents

    Answer (considering the conversation history if relevant):
    Answer in the same language as the question :
    """

    response = llm.invoke(prompt)

    print(f"\n Réponse:\n{response.content}")

    # Save to history
    save_to_history(session_id, user_id, "user", question)
    save_to_history(session_id, user_id, "assistant", response.content)

# 8. FERMETURE
cur.close()
conn.close()
print("\n Session terminée. Historique sauvegardé.")