# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Contract Validator
# ==============================================================================
# Fichier: src/core/contract_validator.py
# Description: Élimine les hallucinations d'API en validant les contrats
#              entre les composants du pipeline.
# ==============================================================================

from functools import wraps
from typing import Dict, Any, Callable, Optional, List, Set, Union
from datetime import datetime, timezone
import logging
import inspect

logger = logging.getLogger(__name__)


class ContractValidator:
    """
    Valide les contrats entre les composants du pipeline.
    
    Cette classe fournit des méthodes statiques pour valider :
    - L'existence de méthodes sur des objets
    - La cohérence des statuts
    - Les chemins d'import
    - La conformité des signatures de fonctions
    """
    
    @staticmethod
    def validate_method_exists(obj: Any, method_name: str) -> bool:
        """
        Vérifie si une méthode existe sur un objet.
        
        Args:
            obj: L'objet à inspecter
            method_name: Nom de la méthode à vérifier
            
        Returns:
            bool: True si la méthode existe et est callable
        """
        return hasattr(obj, method_name) and callable(getattr(obj, method_name))
    
    @staticmethod
    def validate_method_signature(obj: Any, method_name: str, expected_params: int) -> bool:
        """
        Vérifie la signature d'une méthode.
        
        Args:
            obj: L'objet à inspecter
            method_name: Nom de la méthode
            expected_params: Nombre de paramètres attendus
            
        Returns:
            bool: True si la signature correspond
        """
        if not ContractValidator.validate_method_exists(obj, method_name):
            return False
        
        method = getattr(obj, method_name)
        sig = inspect.signature(method)
        params = [p for p in sig.parameters.values() if p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)]
        return len(params) == expected_params
    
    @staticmethod
    def validate_status_consistency(status: str, allowed_statuses: Union[Set[str], List[str]]) -> bool:
        """
        Valide la cohérence d'un statut par rapport à une liste autorisée.
        
        Args:
            status: Statut à valider
            allowed_statuses: Ensemble ou liste des statuts autorisés
            
        Returns:
            bool: True si le statut est valide
        """
        if isinstance(allowed_statuses, list):
            allowed_statuses = set(allowed_statuses)
        return status.lower() in {s.lower() for s in allowed_statuses}
    
    @staticmethod
    def validate_import_path(module_path: str) -> bool:
        """
        Vérifie si un module peut être importé.
        
        Args:
            module_path: Chemin du module (ex: "src.core.models")
            
        Returns:
            bool: True si le module existe
        """
        try:
            __import__(module_path)
            return True
        except ImportError:
            return False
    
    @staticmethod
    def validate_object_contract(obj: Any, required_attrs: List[str], required_methods: List[str]) -> Dict[str, bool]:
        """
        Valide un contrat complet sur un objet.
        
        Args:
            obj: L'objet à valider
            required_attrs: Liste des attributs requis
            required_methods: Liste des méthodes requises
            
        Returns:
            Dict[str, bool]: Résultats de validation par élément
        """
        results = {}
        
        for attr in required_attrs:
            results[f"attr_{attr}"] = hasattr(obj, attr)
        
        for method in required_methods:
            results[f"method_{method}"] = ContractValidator.validate_method_exists(obj, method)
        
        return results
    
    @staticmethod
    def get_missing_attrs(obj: Any, required_attrs: List[str]) -> List[str]:
        """
        Retourne la liste des attributs manquants sur un objet.
        
        Args:
            obj: L'objet à inspecter
            required_attrs: Liste des attributs requis
            
        Returns:
            List[str]: Attributs manquants
        """
        return [attr for attr in required_attrs if not hasattr(obj, attr)]
    
    @staticmethod
    def get_missing_methods(obj: Any, required_methods: List[str]) -> List[str]:
        """
        Retourne la liste des méthodes manquantes sur un objet.
        
        Args:
            obj: L'objet à inspecter
            required_methods: Liste des méthodes requises
            
        Returns:
            List[str]: Méthodes manquantes
        """
        return [method for method in required_methods if not ContractValidator.validate_method_exists(obj, method)]


def validate_contract(required_methods: Optional[List[str]] = None, required_attrs: Optional[List[str]] = None):
    """
    Décorateur pour valider qu'un objet implémente bien un contrat.
    
    Args:
        required_methods: Liste des méthodes requises
        required_attrs: Liste des attributs requis
        
    Returns:
        Callable: Décorateur configuré
    """
    required_methods = required_methods or []
    required_attrs = required_attrs or []
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            # Vérification des méthodes requises
            missing_methods = ContractValidator.get_missing_methods(self, required_methods)
            if missing_methods:
                raise AttributeError(
                    f"Méthodes requises manquantes sur {self.__class__.__name__}: {', '.join(missing_methods)}"
                )
            
            # Vérification des attributs requis
            missing_attrs = ContractValidator.get_missing_attrs(self, required_attrs)
            if missing_attrs:
                raise AttributeError(
                    f"Attributs requis manquants sur {self.__class__.__name__}: {', '.join(missing_attrs)}"
                )
            
            return await func(self, *args, **kwargs)
        return wrapper
    return decorator


def require_method(method_name: str):
    """
    Décorateur pour exiger une méthode sur l'objet.
    
    Args:
        method_name: Nom de la méthode requise
        
    Returns:
        Callable: Décorateur configuré
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            if not ContractValidator.validate_method_exists(self, method_name):
                raise AttributeError(
                    f"Méthode requise '{method_name}' manquante sur {self.__class__.__name__}"
                )
            return await func(self, *args, **kwargs)
        return wrapper
    return decorator


# ==============================================================================
# TEST UNITAIRE (si exécuté directement)
# ==============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Smart Contract Dev Pipeline 2.0 - Contract Validator")
    print("=" * 60)
    
    # Test de la classe
    class TestClass:
        def existing_method(self):
            pass
        
        attr1 = "value"
        attr2 = "value2"
    
    obj = TestClass()
    
    # Test validate_method_exists
    print("\n📋 Test validate_method_exists:")
    print(f"  existing_method: {ContractValidator.validate_method_exists(obj, 'existing_method')}")
    print(f"  nonexistent_method: {ContractValidator.validate_method_exists(obj, 'nonexistent_method')}")
    
    # Test validate_import_path
    print("\n📋 Test validate_import_path:")
    print(f"  src.core.models: {ContractValidator.validate_import_path('src.core.models')}")
    print(f"  src.core.nonexistent: {ContractValidator.validate_import_path('src.core.nonexistent')}")
    
    # Test validate_object_contract
    print("\n📋 Test validate_object_contract:")
    results = ContractValidator.validate_object_contract(
        obj,
        required_attrs=["attr1", "attr3"],
        required_methods=["existing_method", "nonexistent_method"]
    )
    for key, value in results.items():
        print(f"  {key}: {value}")
    
    # Test get_missing_attrs
    print("\n📋 Test get_missing_attrs:")
    missing = ContractValidator.get_missing_attrs(obj, ["attr1", "attr3", "attr4"])
    print(f"  Attributs manquants: {missing}")
    
    # Test get_missing_methods
    print("\n📋 Test get_missing_methods:")
    missing = ContractValidator.get_missing_methods(obj, ["existing_method", "nonexistent_method"])
    print(f"  Méthodes manquantes: {missing}")
    
    # Test du décorateur
    print("\n📋 Test du décorateur @validate_contract:")
    
    @validate_contract(required_methods=["existing_method"])
    class ValidClass:
        def existing_method(self):
            pass
        
        async def run(self):
            return "OK"
    
    valid_instance = ValidClass()
    
    @validate_contract(required_methods=["missing_method"])
    class InvalidClass:
        async def run(self):
            return "OK"
    
    invalid_instance = InvalidClass()
    
    try:
        # Ceci devrait fonctionner
        result = await valid_instance.run()
        print(f"  ✅ ValidClass.run() = {result}")
    except AttributeError as e:
        print(f"  ❌ ValidClass.run() a échoué: {e}")
    
    try:
        # Ceci devrait échouer
        result = await invalid_instance.run()
        print(f"  ✅ InvalidClass.run() = {result}")
    except AttributeError as e:
        print(f"  ❌ InvalidClass.run() a échoué: {e}")
    
    print("\n✅ Tests terminés.")