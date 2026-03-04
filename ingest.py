import os
import psycopg2
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings

load_dotenv()

# PostgreSQL connection
conn = psycopg2.connect(
    dbname="ma_base_vector",
    user="postgres",
    password="Yacine-96",
    host="localhost",
    port="5433"
)
cur = conn.cursor()

embeddings = OpenAIEmbeddings()

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200
)

documents_folder = "documents"

for file in os.listdir(documents_folder):
    file_path = os.path.join(documents_folder, file)

    if file.endswith(".pdf"):
        loader = PyPDFLoader(file_path)
    elif file.endswith(".docx"):
        loader = Docx2txtLoader(file_path)
    else:
        continue

    print(f"Processing: {file}")

    raw_docs = loader.load()
    chunks = text_splitter.split_documents(raw_docs)

    for chunk in chunks:
        vector = embeddings.embed_query(chunk.page_content)

        cur.execute(
            "INSERT INTO documents (content, source, embedding) VALUES (%s, %s, %s)",
            (chunk.page_content, file, vector)
        )

conn.commit()
cur.close()
conn.close()

print("✅ Ingestion complete for all PDFs and DOCX files.")