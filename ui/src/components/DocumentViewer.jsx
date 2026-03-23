import { useEffect, useRef, useState } from "react";
import { documentDownloadUrl, uploadDocument } from "../api";

const MIME_ICONS = {
  "application/pdf":   "📄",
  "image/png":         "🖼️",
  "image/jpeg":        "🖼️",
  "image/jpg":         "🖼️",
  "application/msword": "📝",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "📝",
};

const STATUS_COLORS = {
  pending:  "bg-amber-100 text-amber-700",
  reviewed: "bg-blue-100 text-blue-700",
  accepted: "bg-green-100 text-green-700",
  rejected: "bg-red-100 text-red-700",
};

function formatBytes(n) {
  if (!n) return "—";
  if (n < 1024) return `${n} o`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} Ko`;
  return `${(n / 1048576).toFixed(1)} Mo`;
}

// ── Overlay de prévisualisation ───────────────────────────────────────────────

function DocPreview({ doc, onClose }) {
  const isImage = doc.mime_type?.startsWith("image/");
  const isPdf   = doc.mime_type === "application/pdf";

  // Escape key
  useEffect(() => {
    const h = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 bg-black/80 z-[80] flex flex-col items-center justify-center p-4"
      onClick={onClose}
    >
      {/* Barre de titre */}
      <div
        className="w-full max-w-4xl bg-white rounded-t-xl px-4 py-3 flex items-center justify-between"
        onClick={(e) => e.stopPropagation()}
      >
        <span className="text-sm font-medium text-gray-800 truncate max-w-xs">
          {doc.filename}
        </span>
        <div className="flex items-center gap-2">
          <a
            href={doc.url}
            download={doc.filename}
            className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600
              rounded-lg hover:bg-gray-50 transition-colors"
            onClick={(e) => e.stopPropagation()}
          >
            ↓ Télécharger
          </a>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-800 transition-colors text-xl font-bold px-2"
            aria-label="Fermer"
          >
            ×
          </button>
        </div>
      </div>

      {/* Visualiseur */}
      <div
        className="w-full max-w-4xl bg-white rounded-b-xl overflow-hidden flex-1 max-h-[80vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {isImage && (
          <div className="w-full h-full flex items-center justify-center bg-gray-50 p-4 overflow-auto">
            <img
              src={doc.url}
              alt={doc.filename}
              className="max-w-full max-h-[75vh] object-contain rounded shadow-sm"
            />
          </div>
        )}

        {isPdf && (
          <iframe
            src={doc.url}
            title={doc.filename}
            className="w-full h-[75vh] border-0"
          />
        )}

        {!isImage && !isPdf && (
          <div className="flex flex-col items-center justify-center h-40 text-gray-500 gap-3">
            <span className="text-4xl">📄</span>
            <p className="text-sm">Aperçu non disponible pour ce type de fichier.</p>
            <a
              href={doc.url}
              download={doc.filename}
              className="text-xs px-4 py-2 bg-bnmblue text-white rounded-lg hover:bg-blue-900"
            >
              ↓ Télécharger
            </a>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Composant principal ───────────────────────────────────────────────────────

export default function DocumentViewer({ ticketId, documents = [], onRefresh }) {
  const [uploading, setUploading] = useState(false);
  const [error, setError]         = useState(null);
  const [previewDoc, setPreviewDoc] = useState(null);
  const inputRef                  = useRef(null);

  async function handleFiles(files) {
    if (!files?.length) return;
    setUploading(true);
    setError(null);
    try {
      for (const file of Array.from(files)) {
        await uploadDocument(ticketId, file);
      }
      onRefresh?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  function onDrop(e) {
    e.preventDefault();
    handleFiles(e.dataTransfer.files);
  }

  return (
    <>
      <div className="space-y-3">

        {/* Zone upload drag-and-drop */}
        <div
          onDrop={onDrop}
          onDragOver={(e) => e.preventDefault()}
          onClick={() => !uploading && inputRef.current?.click()}
          className={`border-2 border-dashed rounded-xl p-4 text-center cursor-pointer
            transition-colors ${uploading
              ? "border-bnmblue bg-blue-50 cursor-wait"
              : "border-gray-300 hover:border-bnmblue hover:bg-blue-50"}`}
        >
          <input
            ref={inputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => handleFiles(e.target.files)}
          />
          <p className="text-sm text-gray-500">
            {uploading
              ? "Envoi en cours…"
              : "📎 Glisser un fichier ici ou cliquer pour ajouter"}
          </p>
        </div>

        {error && (
          <p className="text-xs text-red-600 bg-red-50 rounded px-2 py-1">
            ⚠️ {error}
          </p>
        )}

        {/* Liste des documents */}
        {documents.length === 0 ? (
          <p className="text-xs text-gray-400 text-center py-2">
            Aucun document joint
          </p>
        ) : (
          <div className="space-y-1.5">
            {documents.map((doc) => {
              const icon = MIME_ICONS[doc.mime_type] || "📎";
              const sc   = STATUS_COLORS[doc.status] || "bg-gray-100 text-gray-500";
              const url  = documentDownloadUrl(ticketId, doc.doc_id);
              return (
                <div
                  key={doc.doc_id}
                  className="flex items-center gap-2 p-2 bg-white border border-gray-200
                    rounded-lg hover:border-bnmblue transition-colors"
                >
                  <span className="text-lg shrink-0">{icon}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-gray-800 truncate">
                      {doc.filename}
                    </p>
                    <p className="text-xs text-gray-400">
                      {formatBytes(doc.size_bytes)} ·{" "}
                      {new Date(doc.uploaded_at).toLocaleDateString("fr-FR")} ·{" "}
                      {doc.uploaded_by === "client" ? "🙋 Client" : "👤 Agent"}
                    </p>
                  </div>
                  <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium shrink-0 ${sc}`}>
                    {doc.status}
                  </span>
                  {/* Bouton consulter inline */}
                  <button
                    onClick={() => setPreviewDoc({
                      url,
                      mime_type: doc.mime_type,
                      filename:  doc.filename,
                    })}
                    className="text-xs px-2.5 py-1 bg-bnmblue text-white rounded-lg
                      hover:bg-blue-900 transition-colors shrink-0"
                    title="Consulter en ligne"
                  >
                    👁 Consulter
                  </button>
                  {/* Télécharger */}
                  <a
                    href={url}
                    download={doc.filename}
                    className="text-bnmblue hover:text-blue-900 text-xs font-medium shrink-0 ml-1"
                    onClick={(e) => e.stopPropagation()}
                    title="Télécharger"
                  >
                    ↓
                  </a>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Prévisualisation inline */}
      {previewDoc && (
        <DocPreview doc={previewDoc} onClose={() => setPreviewDoc(null)} />
      )}
    </>
  );
}
