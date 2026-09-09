# src/persistence/knowledge_base.py

"""
Knowledge base for the Smart Contract Dev Pipeline.
F27 – src/persistence/knowledge_base.py

Role Fonctionnel : Client d'acces a la base vectorielle ChromaDB pour le RAG.
Ce module fournit une interface complete pour interagir avec ChromaDB,
permettant:
- L'indexation vectorielle de documents et artefacts
- La recherche par similarite semantique (RAG)
- Le filtrage par metadonnees
- La gestion des collections
- La mise en cache des embeddings
- Le support de multiples sources de connaissances

La base de connaissances est utilisee par les agents pour enrichir
leur contexte avec des informations pertinentes extraites de la documentation,
des contrats existants et des bonnes pratiques.
"""
import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions
from typing import Dict, List, Any, Optional, Union, Set
from datetime import datetime, timezone
import logging
import json
import hashlib
import asyncio
from enum import Enum
from dataclasses import dataclass, field

# Import des modules du pipeline
from src.llm.llm_client import LLMClient
from src.core.exceptions import KnowledgeBaseError

# Tentative d'import des settings avec fallback
try:
    from src.config.settings import settings
except ImportError:
    # Fallback pour les tests
    class _Settings:
        chroma_host = "localhost"
        chroma_port = 8000
    settings = _Settings()

# Configuration du logging
logger = logging.getLogger(__name__)


class DocumentType(str, Enum):
    """
    Types de documents dans la base de connaissances.
    """
    CONTRACT = "contract"          # Contrat Solidity
    DOCUMENTATION = "documentation" # Documentation
    BEST_PRACTICE = "best_practice" # Bonnes pratiques
    SECURITY = "security"          # Securite
    TUTORIAL = "tutorial"          # Tutoriel
    SPECIFICATION = "specification" # Specification
    TEST = "test"                  # Test
    DEPLOYMENT = "deployment"      # Deploiement
    AUDIT = "audit"                # Audit
    CODE_SNIPPET = "code_snippet"  # Extrait de code
    CONFIGURATION = "configuration" # Configuration
    OTHER = "other"                # Autre


@dataclass
class Document:
    """
    Represente un document dans la base de connaissances.

    Attributes:
        id (str): Identifiant unique du document
        content (str): Contenu textuel
        metadata (Dict): Metadonnees du document
        embedding (Optional[List[float]]): Embedding du document
        document_type (DocumentType): Type de document
        source (str): Source du document
        created_at (datetime): Date de creation
        updated_at (datetime): Date de mise a jour
        version (str): Version du document
        tags (Set[str]): Tags pour la recherche
    """
    id: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None
    document_type: DocumentType = DocumentType.OTHER
    source: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    version: str = "1.0.0"
    tags: Set[str] = field(default_factory=set)

    def to_dict(self) -> Dict:
        """Convertit le document en dictionnaire."""
        return {
            "id": self.id,
            "content": self.content,
            "metadata": self.metadata,
            "document_type": self.document_type.value,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "version": self.version,
            "tags": list(self.tags)
        }


@dataclass
class SearchResult:
    """
    Resultat d'une recherche.

    Attributes:
        document: Document trouve
        score: Score de similarite
        metadata: Metadonnees supplementaires
    """
    document: Document
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convertit le resultat en dictionnaire."""
        return {
            "document": self.document.to_dict(),
            "score": self.score,
            "metadata": self.metadata
        }


class KnowledgeBase:
    """
    Wrapper autour de ChromaDB pour l'indexation vectorielle.

    Cette classe fournit une interface complete pour interagir avec
    la base de connaissances vectorielle, avec support du RAG.

    Attributes:
        client (chromadb.HttpClient): Client ChromaDB
        collection (chromadb.Collection): Collection active
        collection_name (str): Nom de la collection
        llm (Optional[LLMClient]): Client LLM pour les embeddings
        embedding_function (Optional): Fonction d'embedding
        cache_enabled (bool): Activer la mise en cache
        _embedding_cache (Dict): Cache des embeddings
        _stats (Dict): Statistiques d'utilisation
    """

    def __init__(
        self,
        collection_name: str = "web3_docs",
        llm_client: Optional[LLMClient] = None,
        embedding_model: str = "text-embedding-ada-002",
        cache_enabled: bool = True,
        host: Optional[str] = None,
        port: Optional[int] = None
    ):
        """
        Initialise la base de connaissances.

        Args:
            collection_name: Nom de la collection ChromaDB
            llm_client: Client LLM pour les embeddings
            embedding_model: Modele d'embedding a utiliser
            cache_enabled: Activer la mise en cache
            host: Hote ChromaDB (utilise settings par defaut)
            port: Port ChromaDB (utilise settings par defaut)

        Raises:
            KnowledgeBaseError: Si la connexion a ChromaDB echoue
        """
        self.collection_name = collection_name
        self.llm = llm_client
        self.embedding_model = embedding_model
        self.cache_enabled = cache_enabled
        self._embedding_cache: Dict[str, List[float]] = {}
        self._stats = {
            "documents_added": 0,
            "queries": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "errors": 0
        }

        try:
            # Initialisation du client ChromaDB
            self.client = chromadb.HttpClient(
                host=host or getattr(settings, 'chroma_host', 'localhost'),
                port=port or getattr(settings, 'chroma_port', 8000),
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )

            # Creation ou recuperation de la collection
            self.collection = self.client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"}
            )

            # Fonction d'embedding (si pas de LLM, utiliser le modele par defaut)
            if not self.llm:
                self.embedding_function = embedding_functions.DefaultEmbeddingFunction()
            else:
                self.embedding_function = None

            logger.info(f"KnowledgeBase initialized: {collection_name}")

        except Exception as e:
            logger.error(f"Failed to connect to ChromaDB: {str(e)}")
            raise KnowledgeBaseError(f"Failed to connect to ChromaDB: {e}")

    def _sanitize_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Union[str, int, float, bool]]:
        """
        Nettoie les métadonnées pour s'assurer qu'elles sont compatibles avec ChromaDB
        (conversion des dictionnaires/listes en chaînes JSON).
        """
        sanitized = {}
        for k, v in metadata.items():
            if isinstance(v, (str, int, float, bool)):
                sanitized[k] = v
            elif v is None:
                sanitized[k] = ""
            else:
                try:
                    sanitized[k] = json.dumps(v)
                except Exception:
                    sanitized[k] = str(v)
        return sanitized

    # =========================================================================
    # GESTION DES DOCUMENTS
    # =========================================================================

    async def add_document(
        self,
        document: Document,
        generate_embedding: bool = True
    ) -> str:
        """
        Ajoute un document a la base de connaissances.

        Args:
            document: Document a ajouter
            generate_embedding: Generer l'embedding (defaut: True)

        Returns:
            str: ID du document ajoute

        Raises:
            KnowledgeBaseError: Si l'ajout echoue
        """
        try:
            # Generation de l'embedding si necessaire
            if generate_embedding and not document.embedding:
                document.embedding = await self._get_embedding(document.content)

            # Preparation des donnees et nettoyage des métadonnées pour ChromaDB
            base_metadata = document.metadata.copy() if document.metadata else {}
            base_metadata["document_type"] = document.document_type.value
            base_metadata["source"] = document.source
            base_metadata["version"] = document.version
            base_metadata["created_at"] = document.created_at.isoformat() if document.created_at else ""
            base_metadata["updated_at"] = document.updated_at.isoformat() if document.updated_at else ""
            base_metadata["tags"] = ",".join(document.tags) if document.tags else ""

            metadata = self._sanitize_metadata(base_metadata)

            # Ajout a ChromaDB
            if document.embedding:
                self.collection.add(
                    ids=[document.id],
                    embeddings=[document.embedding],
                    documents=[document.content],
                    metadatas=[metadata]
                )
            else:
                self.collection.add(
                    ids=[document.id],
                    documents=[document.content],
                    metadatas=[metadata]
                )

            self._stats["documents_added"] += 1

            logger.info(f"Document added: {document.id} ({document.document_type.value})")
            return document.id

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Failed to add document {document.id}: {str(e)}")
            raise KnowledgeBaseError(f"Failed to add document: {e}")

    async def add_documents(
        self,
        documents: List[Document],
        generate_embedding: bool = True
    ) -> List[str]:
        """
        Ajoute plusieurs documents.

        Args:
            documents: Liste des documents
            generate_embedding: Generer les embeddings

        Returns:
            List[str]: IDs des documents ajoutes
        """
        ids = []
        for document in documents:
            try:
                doc_id = await self.add_document(document, generate_embedding)
                ids.append(doc_id)
            except KnowledgeBaseError as e:
                logger.error(f"Failed to add document {document.id}: {str(e)}")
        return ids

    async def add_artifact(self, artifact: Dict) -> str:
        """
        Ajoute un artefact a la base de connaissances.

        Args:
            artifact: Artefact a ajouter

        Returns:
            str: ID du document cree

        Raises:
            KnowledgeBaseError: Si l'ajout echoue
        """
        try:
            # Extraction des donnees
            content = artifact.get("content", "")
            artifact_type = artifact.get("type", "other")
            metadata = artifact.get("metadata", {})
            artifact_id = artifact.get("id", f"art_{datetime.now(timezone.utc).timestamp()}")

            # Conversion du type
            try:
                doc_type = DocumentType(artifact_type)
            except ValueError:
                doc_type = DocumentType.OTHER

            # Creation du document
            document = Document(
                id=artifact_id,
                content=content,
                metadata=metadata,
                document_type=doc_type,
                source=artifact.get("source", "unknown"),
                tags=set(metadata.get("tags", [])),
                version=artifact.get("version", "1.0.0")
            )

            return await self.add_document(document)

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Failed to add artifact: {str(e)}")
            raise KnowledgeBaseError(f"Failed to add artifact: {e}")

    async def get_document(self, doc_id: str) -> Optional[Document]:
        """
        Recupere un document par ID.

        Args:
            doc_id: ID du document

        Returns:
            Optional[Document]: Document ou None
        """
        try:
            result = self.collection.get(ids=[doc_id])
            if not result or not result.get("ids") or len(result["ids"]) == 0:
                return None

            idx = 0
            metadata = result["metadatas"][idx] if result.get("metadatas") and result["metadatas"] else {}
            doc_type_str = metadata.get("document_type", "other")
            try:
                doc_type = DocumentType(doc_type_str)
            except ValueError:
                doc_type = DocumentType.OTHER

            return Document(
                id=result["ids"][idx],
                content=result["documents"][idx] if result.get("documents") else "",
                metadata=metadata,
                document_type=doc_type,
                source=metadata.get("source", ""),
                tags=set(metadata.get("tags", "").split(",")) if metadata.get("tags") else set()
            )

        except Exception as e:
            logger.error(f"Failed to get document {doc_id}: {str(e)}")
            return None

    async def delete_document(self, doc_id: str) -> bool:
        """
        Supprime un document.

        Args:
            doc_id: ID du document

        Returns:
            bool: True si supprime
        """
        try:
            self.collection.delete(ids=[doc_id])
            logger.info(f"Document deleted: {doc_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete document {doc_id}: {str(e)}")
            return False

    async def update_document(
        self,
        doc_id: str,
        content: Optional[str] = None,
        metadata: Optional[Dict] = None,
        generate_embedding: bool = True
    ) -> bool:
        """
        Met a jour un document.

        Args:
            doc_id: ID du document
            content: Nouveau contenu (optionnel)
            metadata: Nouvelles metadonnees (optionnel)
            generate_embedding: Generer l'embedding

        Returns:
            bool: True si mis a jour
        """
        try:
            # Recuperation du document existant
            current = await self.get_document(doc_id)
            if not current:
                return False

            # Mise a jour
            if content is not None:
                current.content = content
                current.embedding = await self._get_embedding(content) if generate_embedding else None

            if metadata is not None:
                current.metadata.update(metadata)

            current.updated_at = datetime.now(timezone.utc)

            # Re-ajout du document (suppression + ajout)
            await self.delete_document(doc_id)
            await self.add_document(current, generate_embedding=generate_embedding)

            logger.info(f"Document updated: {doc_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to update document {doc_id}: {str(e)}")
            return False

    # =========================================================================
    # RECHERCHE (RAG)
    # =========================================================================

    async def query(
        self,
        text: str,
        top_k: int = 5,
        document_type: Optional[Union[DocumentType, str]] = None,
        source: Optional[str] = None,
        tags: Optional[List[str]] = None,
        min_score: float = 0.0,
        include_metadata: bool = True
    ) -> List[SearchResult]:
        """
        Interroge la base de connaissances par similarite.

        Args:
            text: Texte de la requete
            top_k: Nombre de resultats
            document_type: Filtrer par type de document
            source: Filtrer par source
            tags: Filtrer par tags
            min_score: Score minimum (0-1)
            include_metadata: Inclure les metadonnees

        Returns:
            List[SearchResult]: Resultats de recherche

        Raises:
            KnowledgeBaseError: Si la recherche echoue
        """
        self._stats["queries"] += 1

        try:
            # Generation de l'embedding de la requete
            query_embedding = await self._get_embedding(text)

            # Construction robuste des filtres avec $and si nécessaire
            where_conditions = []
            if document_type:
                doc_type_value = document_type.value if isinstance(document_type, DocumentType) else document_type
                where_conditions.append({"document_type": doc_type_value})
            if source:
                where_conditions.append({"source": source})

            if len(where_conditions) == 1:
                where = where_conditions[0]
            elif len(where_conditions) > 1:
                where = {"$and": where_conditions}
            else:
                where = None

            # Recherche
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=where,
                include=["documents", "metadatas", "distances"]
            )

            # Construction des resultats
            search_results = []
            if results and results.get("ids") and results["ids"][0]:
                for i, doc_id in enumerate(results["ids"][0]):
                    # Calcul du score de similarite (cosine -> 1 - distance)
                    distance = results["distances"][0][i] if results.get("distances") and results["distances"][0] else 0.5
                    score = 1 - min(distance, 1.0)  # distance est généralement entre 0 et 2

                    if score < min_score:
                        continue

                    # Construction du document
                    metadata = results["metadatas"][0][i] if results.get("metadatas") and results["metadatas"][0] else {}
                    doc_type_str = metadata.get("document_type", "other")
                    try:
                        doc_type = DocumentType(doc_type_str)
                    except ValueError:
                        doc_type = DocumentType.OTHER

                    # Filtrage des tags (post-query)
                    if tags:
                        doc_tags = set(metadata.get("tags", "").split(",")) if metadata.get("tags") else set()
                        if not any(t in doc_tags for t in tags):
                            continue

                    doc = Document(
                        id=doc_id,
                        content=results["documents"][0][i] if results.get("documents") and results["documents"][0] else "",
                        metadata=metadata,
                        document_type=doc_type,
                        source=metadata.get("source", ""),
                        tags=set(metadata.get("tags", "").split(",")) if metadata.get("tags") else set()
                    )

                    search_results.append(SearchResult(
                        document=doc,
                        score=score,
                        metadata={"rank": i + 1}
                    ))

            logger.debug(f"Query returned {len(search_results)} results")
            return search_results

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Query failed: {str(e)}")
            raise KnowledgeBaseError(f"Query failed: {e}")

    async def query_by_content(
        self,
        content: str,
        top_k: int = 5,
        **kwargs
    ) -> List[SearchResult]:
        """
        Alias pour query().

        Args:
            content: Contenu a rechercher
            top_k: Nombre de resultats
            **kwargs: Arguments supplementaires

        Returns:
            List[SearchResult]: Resultats de recherche
        """
        return await self.query(content, top_k, **kwargs)

    async def query_context(
        self,
        query: str,
        n_results: int = 3,
        **kwargs
    ) -> List[str]:
        """
        Recupere le contexte pour le RAG.

        Args:
            query: Requete
            n_results: Nombre de resultats
            **kwargs: Arguments supplementaires

        Returns:
            List[str]: Contenus des documents

        Raises:
            KnowledgeBaseError: Si la recherche echoue
        """
        results = await self.query(query, top_k=n_results, **kwargs)
        return [r.document.content for r in results if r.score >= 0.5]

    # =========================================================================
    # GESTION DES COLLECTIONS
    # =========================================================================

    async def list_collections(self) -> List[str]:
        """
        Liste toutes les collections.

        Returns:
            List[str]: Noms des collections
        """
        try:
            collections = self.client.list_collections()
            return [c.name for c in collections]
        except Exception as e:
            logger.error(f"Failed to list collections: {str(e)}")
            return []

    async def switch_collection(self, collection_name: str) -> bool:
        """
        Change la collection active.

        Args:
            collection_name: Nom de la collection

        Returns:
            bool: True si changement reussi
        """
        try:
            self.collection = self.client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"}
            )
            self.collection_name = collection_name
            logger.info(f"Switched to collection: {collection_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to switch collection: {str(e)}")
            return False

    async def delete_collection(self, collection_name: str) -> bool:
        """
        Supprime une collection.

        Args:
            collection_name: Nom de la collection

        Returns:
            bool: True si supprime
        """
        try:
            self.client.delete_collection(collection_name)
            logger.info(f"Collection deleted: {collection_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete collection: {str(e)}")
            return False

    # =========================================================================
    # STATISTIQUES
    # =========================================================================

    async def get_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques de la base de connaissances.

        Returns:
            Dict: Statistiques detaillees
        """
        try:
            collection_stats = self.collection.count()
        except Exception:
            collection_stats = 0

        total_cache_ops = self._stats["cache_hits"] + self._stats["cache_misses"]
        return {
            **self._stats,
            "collection_name": self.collection_name,
            "document_count": collection_stats,
            "cache_hit_rate": (
                self._stats["cache_hits"] / total_cache_ops
                if total_cache_ops > 0
                else 0
            )
        }

    # =========================================================================
    # EMBEDDINGS
    # =========================================================================

    async def _get_embedding(self, text: str) -> List[float]:
        """
        Genere un embedding pour un texte.

        Args:
            text: Texte a embedder

        Returns:
            List[float]: Embedding

        Raises:
            KnowledgeBaseError: Si l'embedding echoue
        """
        # Verification du cache
        cache_key = hashlib.md5(text.encode('utf-8')).hexdigest()
        if self.cache_enabled and cache_key in self._embedding_cache:
            self._stats["cache_hits"] += 1
            return self._embedding_cache[cache_key]

        self._stats["cache_misses"] += 1

        try:
            # Utilisation du LLM si disponible
            if self.llm:
                if hasattr(self.llm, 'embed'):
                    # Appel async si disponible
                    if asyncio.iscoroutinefunction(self.llm.embed):
                        embedding = await self.llm.embed(text)
                    else:
                        # Fallback: exécution synchrone dans un thread
                        try:
                            loop = asyncio.get_running_loop()
                        except RuntimeError:
                            loop = asyncio.get_event_loop()
                        embedding = await loop.run_in_executor(None, self.llm.embed, text)
                else:
                    # Fallback: utiliser l'embedding function de ChromaDB
                    embedding = await self._get_embedding_fallback(text)
            else:
                embedding = await self._get_embedding_fallback(text)

            # Mise en cache
            if self.cache_enabled:
                self._embedding_cache[cache_key] = embedding

            return embedding

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Failed to generate embedding: {str(e)}")
            raise KnowledgeBaseError(f"Failed to generate embedding: {e}")

    async def _get_embedding_fallback(self, text: str) -> List[float]:
        """
        Methode de fallback pour les embeddings.

        Args:
            text: Texte a embedder

        Returns:
            List[float]: Embedding
        """
        # Utilisation de l'embedding function de ChromaDB (synchrone)
        if self.embedding_function:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.embedding_function([text])
            )
            return result[0]

        # Dernier recours : embedding basé sur SHA256
        import hashlib
        hash_bytes = hashlib.sha256(text.encode('utf-8')).digest()
        return [b / 255.0 for b in hash_bytes[:128]]

    # =========================================================================
    # MAINTENANCE
    # =========================================================================

    async def clear_cache(self) -> None:
        """
        Vide le cache des embeddings.
        """
        cache_size = len(self._embedding_cache)
        self._embedding_cache.clear()
        logger.info(f"Embedding cache cleared ({cache_size} entries)")

    async def clear_collection(self) -> None:
        """
        Vide la collection active.
        """
        try:
            # Recuperation de tous les IDs
            result = self.collection.get()
            if result and result.get("ids"):
                self.collection.delete(ids=result["ids"])
            logger.info(f"Collection cleared: {self.collection_name}")
        except Exception as e:
            logger.error(f"Failed to clear collection: {str(e)}")
            raise KnowledgeBaseError(f"Failed to clear collection: {e}")

    async def optimize(self) -> None:
        """
        Optimise la base de connaissances.
        """
        logger.info("Knowledge base optimized (placeholder)")

    # =========================================================================
    # REPRESENTATION
    # =========================================================================

    def __repr__(self) -> str:
        try:
            count = self.collection.count()
        except Exception:
            count = 0
        return f"<KnowledgeBase(collection='{self.collection_name}', docs={count})>"

    def to_dict(self) -> Dict:
        """
        Convertit la base de connaissances en dictionnaire.

        Returns:
            Dict: Representation
        """
        try:
            count = self.collection.count()
        except Exception:
            count = 0
        return {
            "collection_name": self.collection_name,
            "document_count": count,
            "cache_enabled": self.cache_enabled,
            "cache_size": len(self._embedding_cache),
            "stats": self._stats
        }