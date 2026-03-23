import json
import os
import psycopg2
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

load_dotenv()

conn = psycopg2.connect(
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT")
)
cur = conn.cursor()

embeddings = OpenAIEmbeddings()
llm = ChatOpenAI(model="gpt-4o-mini")

SEP = "══════════════════════════════════════════"

CLASSIFIER_SYSTEM = (
    "Tu es un classificateur bancaire. Analyse la demande client et réponds "
    "UNIQUEMENT en JSON valide avec ce format exact :\n"
    '{"intent": "INFORMATION" | "RECLAMATION" | "VALIDATION", '
    '"confidence": "HIGH" | "MEDIUM" | "LOW", '
    '"reason": "explication courte en français (max 10 mots)"}\n'
    "Ne réponds rien d'autre que ce JSON."
)


def classify_intent(question: str, model) -> dict:
    try:
        messages = [
            SystemMessage(content=CLASSIFIER_SYSTEM),
            HumanMessage(content=question),
        ]
        raw = model.invoke(messages).content.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception:
        return {
            "intent": "INFORMATION",
            "confidence": "LOW",
            "reason": "classification échouée",
        }


question = input("Ask your question: ")

# ── Classification ────────────────────────────────────────────
classification = classify_intent(question, llm)

# ── RAG ───────────────────────────────────────────────────────
question_vector = embeddings.embed_query(question)

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
    context += content + "\n\n"

prompt = f"""
You are an assistant that answers ONLY using the provided context about BNM.
If the answer is not in the context, say you don't know.

Context:
{context}

Question:
{question}

Answer:
"""

response = llm.invoke(prompt)

# ── Affichage ─────────────────────────────────────────────────
print(f"\n{SEP}")
print(" CLASSIFICATION CLIENT")
print(SEP)
print(f" Intention   : {classification.get('intent', 'N/A')}")
print(f" Confiance   : {classification.get('confidence', 'N/A')}")
print(f" Raison      : {classification.get('reason', 'N/A')}")
print(SEP)
print(" RÉPONSE")
print(SEP)
print(f" {response.content}")
print(SEP)

cur.close()
conn.close()
