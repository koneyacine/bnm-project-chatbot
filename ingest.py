"""
ingest.py — Ingestion des documents dans pgvector.

Usage :
  python ingest.py
  python ingest.py --folder /chemin/vers/documents

Formats supportés : .pdf, .docx
"""
import argparse
import os

import psycopg2
from dotenv import load_dotenv
from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()


def ingest(folder: str = "documents") -> None:
    conn = psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
    )
    cur = conn.cursor()

    # S'assurer que la table et l'extension existent
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id        BIGSERIAL PRIMARY KEY,
            content   TEXT,
            source    VARCHAR(500),
            embedding vector(1536)
        );
    """)
    conn.commit()

    embeddings = OpenAIEmbeddings(
        model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-ada-002"),
    )
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
    )

    total = 0
    for file in sorted(os.listdir(folder)):
        path = os.path.join(folder, file)
        if file.endswith(".pdf"):
            loader = PyPDFLoader(path)
        elif file.endswith(".docx"):
            loader = Docx2txtLoader(path)
        else:
            continue

        print(f"  → {file} ...", end="", flush=True)
        raw_docs = loader.load()
        chunks   = splitter.split_documents(raw_docs)

        for chunk in chunks:
            vec = embeddings.embed_query(chunk.page_content)
            cur.execute(
                "INSERT INTO documents (content, source, embedding) "
                "VALUES (%s, %s, %s)",
                (chunk.page_content, file, vec),
            )
        conn.commit()
        print(f" {len(chunks)} chunks")
        total += len(chunks)

    cur.close()
    conn.close()
    print(f"\n✅ Ingestion terminée — {total} chunks insérés.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest documents into pgvector")
    parser.add_argument("--folder", default="documents",
                        help="Dossier contenant les documents (défaut: documents/)")
    args = parser.parse_args()
    ingest(args.folder)
