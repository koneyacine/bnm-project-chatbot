import psycopg2
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from langchain_openai import ChatOpenAI

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

question = input("Ask your question: ")

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

print("\n Answer:\n")
print(response.content)


cur.close()
conn.close()