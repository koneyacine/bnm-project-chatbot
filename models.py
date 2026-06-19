from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
 
 
# ── Message de contexte ──────────────────────────────────────────────
class ContextMessage(BaseModel):
    role: str       # "client" | "conseiller"
    content: str
 
 
# ── Ticket existant (réclamation ou validation) ──────────────────────
class TicketItem(BaseModel):
    id: Optional[str]             = None
    titre: Optional[str]          = None   # ou "title" / "subject"
    title: Optional[str]          = None
    subject: Optional[str]        = None
    statut: Optional[str]         = None   # ou "status"
    status: Optional[str]         = None
    date: Optional[str]           = None   # ou "created_at"
    created_at: Optional[str]     = None
    # champ spécifique validation : documents déjà fournis
    documents_fournis: Optional[List[str]] = Field(default_factory=list)
    documents: Optional[List[str]]         = Field(default_factory=list)
    # champs libres supplémentaires
    extra: Optional[Dict[str, Any]] = None
 
 
# ── Requête principale ───────────────────────────────────────────────
class AttachmentContext(BaseModel):
    attachment_id:      str
    attachment_type:    str
    mime_type:          str
    file_size:          int
    photo_url:          str
    processing_status:  str                = "pending"
    document_type:      Optional[str]      = None
    ocr_text:           Optional[str]      = None
    # Si le téléchargement/ocr a déjà été effectué, contenu_photo contient
    # les informations extraites de la pièce d'identité.
    contenu_photo: Optional[Dict[str, Any]] = None


class AnswerRequest(BaseModel):
    question: str
    context:  List[ContextMessage]         = Field(default_factory=list)
    intent:   Optional[str]                = None
    session_id: Optional[str]             = None
    tickets:  Optional[List[TicketItem]]   = Field(
        default_factory=list,
        description="Liste des tickets existants du client (réclamations ou validations)."
    )
    attachment: Optional[AttachmentContext] = Field(
        default=None,
        description="Contexte de la photo envoyée par le client (optionnel)."
    )


# Modèle structuré pour le contenu extrait d'une pièce d'identité
class IDPhotoContent(BaseModel):
    nom: Optional[str] = Field(None, description="Nom du titulaire")
    prenom: Optional[str] = Field(None, description="Prénom du titulaire")
    numero_identite: Optional[str] = Field(None, description="Numéro d'identité")
    date_naissance: Optional[str] = Field(None, description="Date de naissance (YYYY-MM-DD)")
    date_expiration: Optional[str] = Field(None, description="Date d'expiration (YYYY-MM-DD)")
    

# Requête pour traitement d'une photo de validation
class ProcessValidationRequest(BaseModel):
    type_photo: str  # exemple: 'selfie' | 'identite' | 'inconnu'
    # contenu_photo: données extraites structurées
    contenu_photo: Optional[IDPhotoContent] = Field(
        default=None,
        description="Données extraites de la photo (IDPhotoContent)"
    )
    message: str
    context: List[ContextMessage] = Field(default_factory=list)
    tickets: Optional[List[TicketItem]] = Field(default_factory=list)
 
 
# ── Autres modèles ───────────────────────────────────────────────────
class IntentRequest(BaseModel):
    question: str
    contexte: Optional[List[dict]] = None  # Contexte extrait depuis la requête
 
class IntentResponse(BaseModel):
    intent: str
 
 
class AnswerResponse(BaseModel):
    answer: str
    intent: str
    open_conversation: bool


# ── Document Classification Response ───────────────────────────────
class DocumentClassificationResponse(BaseModel):
    selfie: bool = Field(..., description="True si le visage d'une personne est clairement visible (selfie ou portrait)")
    personne: bool = Field(..., description="True si c'est une photo de personne")
    identite: bool = Field(..., description="True si c'est une identité mauritanienne")
    identite_non_valide: bool = Field(..., description="True si c'est une pièce d'identité non mauritanienne (étrangère)")
    autres: bool = Field(..., description="True si aucun des deux")


# ── ID Info Extraction Response ─────────────────────────────────────
class IDExtractionResponse(BaseModel):
    nom: Optional[str] = Field(None, description="Nom du titulaire")
    prenom: Optional[str] = Field(None, description="Prénom du titulaire")
    date_naissance: Optional[str] = Field(None, description="Date de naissance (YYYY-MM-DD)")
    date_expiration: Optional[str] = Field(None, description="Date d'expiration (YYYY-MM-DD)")
    numero_identite: Optional[str] = Field(None, description="Numéro d'identité")
    nationalite: Optional[str] = Field(None, description="Nationalité")
    lieu_naissance: Optional[str] = Field(None, description="Lieu de naissance")
    sexe: Optional[str] = Field(None, description="Sexe (M/F)")
 