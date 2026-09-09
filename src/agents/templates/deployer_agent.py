# src/agents/templates/deployer_agent.py

"""
Deployer agent for the Smart Contract Dev Pipeline.
F23 – src/agents/templates/deployer_agent.py

Role Fonctionnel : Agent de déploiement responsable de:
- La génération de scripts de déploiement Foundry
- L'exécution des déploiements sur les réseaux cibles
- La vérification des contrats déployés
- La gestion des upgrades (UUPS, Transparent, Beacon)
- La validation des paramètres de déploiement
- Le reporting des transactions et des gas costs
- La gestion des Safe multi-sig

Cet agent est le dernier maillon du pipeline avant la mise en production.
Version intégrant les nouveaux modules système.
"""
from src.agents.base.abstract_agent import AbstractAgent
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime, timezone
import logging
import json
import re
import asyncio
import subprocess
from enum import Enum
from dataclasses import dataclass, field

# Import des modules du pipeline
from src.core.exceptions import PipelineError, LLMError
from src.core.status_manager import normalize_status, status_manager
from src.core.structured_logger import StructuredLogger, LogLevel, LogCategory
from src.core.contract_validator import ContractValidator, validate_contract
from src.core.intelligent_cache import IntelligentCache, CacheStrategy
from src.core.adaptive_retry import AdaptiveRetry, RetryStrategy
from src.llm.llm_client import LLMClient
from src.persistence.knowledge_base import KnowledgeBase

# Configuration du logging
logger = logging.getLogger(__name__)


class Network(str, Enum):
    """
    Réseaux supportés pour le déploiement.
    """
    MAINNET = "mainnet"
    SEPOLIA = "sepolia"
    POLYGON = "polygon"
    ARBITRUM = "arbitrum"
    OPTIMISM = "optimism"
    BASE = "base"
    AVALANCHE = "avalanche"
    BSC = "bsc"
    FANTOM = "fantom"
    LOCAL = "local"


class DeployerStatus(str, Enum):
    """
    Statuts du déploiement.
    """
    PENDING = "pending"
    PREPARING = "preparing"
    DEPLOYING = "deploying"
    VERIFYING = "verifying"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


class UpgradeStrategy(str, Enum):
    """
    Stratégies d'upgrade.
    """
    UUPS = "UUPS"
    TRANSPARENT = "Transparent"
    BEACON = "Beacon"
    DIAMOND = "Diamond"


@dataclass
class DeploymentConfig:
    """
    Configuration de déploiement.

    Attributes:
        network: Réseau cible
        contract_name: Nom du contrat
        contract_path: Chemin du contrat
        constructor_args: Arguments du constructeur
        salt: Salt pour CREATE2 (optionnel)
        verify: Vérifier sur Etherscan
        gas_limit: Limite de gaz
        gas_price: Prix du gaz (optionnel)
        private_key: Clé privée (optionnelle)
        safe_address: Adresse Safe multi-sig
    """
    network: Network
    contract_name: str
    contract_path: str
    constructor_args: Dict[str, Any] = field(default_factory=dict)
    salt: Optional[str] = None
    verify: bool = True
    gas_limit: int = 3000000
    gas_price: Optional[int] = None
    private_key: Optional[str] = None
    safe_address: Optional[str] = None


@dataclass
class DeploymentResult:
    """
    Résultat du déploiement.

    Attributes:
        contract_address: Adresse déployée
        transaction_hash: Hash de la transaction
        block_number: Numéro du bloc
        gas_used: Gaz utilisé
        gas_price: Prix du gaz utilisé
        total_cost: Coût total en ETH
        network: Réseau de déploiement
        verified: Vérifié sur Etherscan
        deployment_time: Temps de déploiement
        errors: Erreurs rencontrées
        abi: ABI du contrat
        bytecode: Bytecode déployé
        metadata: Métadonnées supplémentaires
    """
    contract_address: Optional[str] = None
    transaction_hash: Optional[str] = None
    block_number: Optional[int] = None
    gas_used: Optional[int] = None
    gas_price: Optional[int] = None
    total_cost: Optional[float] = None
    network: str = ""
    verified: bool = False
    deployment_time: float = 0.0
    errors: List[str] = field(default_factory=list)
    abi: Optional[List[Dict]] = None
    bytecode: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convertit le résultat en dictionnaire."""
        return {
            "contract_address": self.contract_address,
            "transaction_hash": self.transaction_hash,
            "block_number": self.block_number,
            "gas_used": self.gas_used,
            "gas_price": self.gas_price,
            "total_cost_eth": self.total_cost,
            "network": self.network,
            "verified": self.verified,
            "deployment_time": self.deployment_time,
            "errors": self.errors,
            "abi_preview": self.abi[:3] if self.abi and len(self.abi) > 3 else self.abi,
            "metadata": self.metadata
        }


class DeployerAgent(AbstractAgent):
    """
    Agent spécialisé dans le déploiement des smart contracts.

    Attributes:
        llm_client (Optional[LLMClient]): Client LLM pour la génération de scripts
        knowledge_base (Optional[KnowledgeBase]): Base de connaissances RAG
        foundry_path (str): Chemin vers Foundry (forge)
        cast_path (str): Chemin vers Cast
        default_network (Network): Réseau par défaut
        safe_threshold (int): Seuil de sécurité Safe
        _deployment_history (List[DeploymentResult]): Historique des déploiements
        _cache (IntelligentCache): Cache des déploiements
        _logger (StructuredLogger): Logger structuré
        _retry_handler (AdaptiveRetry): Système de retry
    """

    def __init__(
        self,
        agent_id: str,
        name: str = "DeployerAgent",
        skills: Optional[List] = None,
        llm_client: Optional[LLMClient] = None,
        knowledge_base: Optional[KnowledgeBase] = None,
        foundry_path: str = "forge",
        cast_path: str = "cast",
        default_network: Network = Network.LOCAL,
        safe_threshold: int = 2,
        cache_enabled: bool = True,
        cache_ttl: int = 3600,
        log_callback=None
    ):
        """
        Initialise l'Agent Deployer.

        Args:
            agent_id: Identifiant unique de l'agent
            name: Nom de l'agent (defaut: "DeployerAgent")
            skills: Liste des compétences (optionnel)
            llm_client: Client LLM pour la génération
            knowledge_base: Base de connaissances RAG
            foundry_path: Chemin vers Foundry (defaut: "forge")
            cast_path: Chemin vers Cast (defaut: "cast")
            default_network: Réseau par défaut (defaut: LOCAL)
            safe_threshold: Seuil de sécurité Safe (defaut: 2)
            cache_enabled: Activer le cache
            cache_ttl: Durée de vie du cache en secondes
            log_callback: Callback pour les logs
        """
        super().__init__(
            agent_id=agent_id,
            name=name,
            skills=skills,
            llm_client=llm_client,
            knowledge_base=knowledge_base,
            log_callback=log_callback
        )
        self.llm_client = llm_client
        self.knowledge_base = knowledge_base
        self.foundry_path = foundry_path
        self.cast_path = cast_path
        self.default_network = default_network
        self.safe_threshold = safe_threshold
        self._deployment_history: List[DeploymentResult] = []

        # Cache intelligent
        self._cache = IntelligentCache(
            default_ttl=cache_ttl,
            max_entries=200,
            strategy=CacheStrategy.ADAPTIVE,
            enable_metrics=True
        )
        if cache_enabled:
            self._cache.start()

        # Logger structuré
        self._logger = StructuredLogger(
            component_name=f"DeployerAgent_{agent_id}",
            log_level=LogLevel.INFO
        )
        self._logger.set_context(agent_id=agent_id)

        # Système de retry adaptatif
        self._retry_handler = AdaptiveRetry(
            base_delay=2.0,
            max_delay=60.0,
            max_retries=5,
            strategy=RetryStrategy.EXPONENTIAL,
            jitter=True,
            retryable_exceptions=(subprocess.TimeoutExpired, PipelineError)
        )

        logger.info(f"DeployerAgent initialized: {agent_id} (default_network={default_network.value})")

    @validate_contract(required_methods=["execute_task"])
    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Exécute le déploiement du contrat.

        Args:
            task_data: Doit contenir:
                - 'contract_path': Chemin du contrat
                - 'contract_name': Nom du contrat
                - 'network': Réseau cible (optionnel)
                - 'constructor_args': Arguments du constructeur (optionnel)
                - 'salt': Salt pour CREATE2 (optionnel)
                - 'verify': Vérifier sur Etherscan (optionnel)

        Returns:
            Dict contenant:
            - 'status': success ou failed
            - 'result': DeploymentResult en dictionnaire
            - 'contract_address': Adresse déployée
            - 'transaction_hash': Hash de la transaction
            - 'network': Réseau de déploiement
        """
        start_time = datetime.now(timezone.utc)
        self._logger.set_context(task_id=task_data.get("task_id", "unknown"))

        try:
            # 1. Extraction des paramètres
            contract_path = task_data.get("contract_path", "")
            contract_name = task_data.get("contract_name", "unknown")
            network_str = task_data.get("network", self.default_network.value)
            constructor_args = task_data.get("constructor_args", {})
            salt = task_data.get("salt")
            verify = task_data.get("verify", True)

            if not contract_path:
                raise ValueError("contract_path is required")

            # 2. Détermination du réseau
            try:
                network = Network(network_str.lower())
            except ValueError:
                self._logger.log_warning(
                    f"Invalid network '{network_str}', using default '{self.default_network.value}'",
                    "invalid_network"
                )
                network = self.default_network

            # 3. Vérification du cache
            cache_key = f"{contract_path}_{contract_name}_{network.value}_{hash(str(constructor_args))}"
            cached_result = await self._cache.get(cache_key)
            if cached_result is not None:
                self._logger.log_info("Cache hit for deployment", "cache_hit")
                return cached_result

            # 4. Préparation du déploiement
            config = DeploymentConfig(
                network=network,
                contract_name=contract_name,
                contract_path=contract_path,
                constructor_args=constructor_args,
                salt=salt,
                verify=verify
            )

            # 5. Génération du script de déploiement
            script = await self._generate_deployment_script(config)

            # 6. Exécution du déploiement
            result = await self._execute_deployment(config, script)

            # 7. Vérification du contrat
            if verify and result.contract_address:
                verified = await self._verify_contract(
                    config.contract_name,
                    config.contract_path,
                    result.contract_address,
                    network
                )
                result.verified = verified

            # 8. Persistance du résultat
            self._deployment_history.append(result)

            # 9. Logging de l'exécution
            await self._log_execution(
                task_data=task_data,
                result={
                    "status": "success",
                    "contract_address": result.contract_address,
                    "transaction_hash": result.transaction_hash,
                    "network": network.value,
                    "verified": result.verified
                },
                success=True,
                duration=(datetime.now(timezone.utc) - start_time).total_seconds()
            )

            # 10. Mise en cache
            result_dict = {
                "status": "success",
                "result": result.to_dict(),
                "contract_address": result.contract_address,
                "transaction_hash": result.transaction_hash,
                "network": network.value,
                "verified": result.verified,
                "metadata": {
                    "execution_time": (datetime.now(timezone.utc) - start_time).total_seconds(),
                    "gas_used": result.gas_used,
                    "total_cost_eth": result.total_cost
                }
            }

            await self._cache.set(
                cache_key,
                result_dict,
                ttl=3600,
                tags=[contract_name, network.value]
            )

            self._logger.log_info(
                f"Deployment completed: {contract_name} -> {result.contract_address}",
                "deployment_completed",
                contract_address=result.contract_address,
                network=network.value,
                verified=result.verified
            )

            return result_dict

        except Exception as e:
            self._logger.log_error(
                f"Deployment failed: {str(e)}",
                e,
                "deployment_failed",
                contract_name=task_data.get("contract_name", "unknown")
            )
            return {
                "status": "failed",
                "error": str(e),
                "execution_time": (datetime.now(timezone.utc) - start_time).total_seconds()
            }
        finally:
            self._logger.clear_context()

    # =========================================================================
    # GÉNÉRATION DE SCRIPT
    # =========================================================================

    async def _generate_deployment_script(
        self,
        config: DeploymentConfig
    ) -> str:
        """
        Génère le script de déploiement Foundry.

        Args:
            config: Configuration de déploiement

        Returns:
            str: Script Solidity
        """
        self._logger.log_info(
            f"Generating deployment script for {config.contract_name}",
            "script_generation_start",
            network=config.network.value
        )

        # Préparation des arguments du constructeur
        args_str = ", ".join([
            f"{k}: {json.dumps(v)}" for k, v in config.constructor_args.items()
        ])

        # Construction du script
        script = f"""
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "{config.contract_path}";

contract Deploy{config.contract_name} is Script {{
    function run() public {{
        // Configuration du déploiement
        uint256 deployerPrivateKey = vm.envUint("PRIVATE_KEY");
        
        // Début du broadcast
        vm.startBroadcast(deployerPrivateKey);
        
        // Déploiement du contrat
        {config.contract_name} contract = new {config.contract_name}(
            {args_str}
        );
        
        vm.stopBroadcast();
        
        // Logging
        console.log("{config.contract_name} deployed at:", address(contract));
    }}
}}
"""
        self._logger.log_debug(
            f"Deployment script generated for {config.contract_name}",
            "script_generated"
        )

        return script

    # =========================================================================
    # EXÉCUTION DU DÉPLOIEMENT
    # =========================================================================

    async def _execute_deployment(
        self,
        config: DeploymentConfig,
        script: str
    ) -> DeploymentResult:
        """
        Exécute le déploiement via Foundry.

        Args:
            config: Configuration de déploiement
            script: Script de déploiement

        Returns:
            DeploymentResult: Résultat du déploiement
        """
        start_time = datetime.now(timezone.utc)
        self._logger.log_info(
            f"Executing deployment for {config.contract_name} on {config.network.value}",
            "deployment_execution_start",
            network=config.network.value
        )

        try:
            import tempfile
            import os

            # Création du répertoire temporaire
            temp_dir = tempfile.mkdtemp(prefix="deploy_")

            try:
                # Écriture du script
                script_path = os.path.join(temp_dir, "Deploy.s.sol")
                with open(script_path, 'w') as f:
                    f.write(script)

                # Détermination de l'URL RPC
                rpc_url = self._get_rpc_url(config.network)

                # Construction de la commande
                cmd = [
                    self.foundry_path,
                    "script",
                    script_path,
                    "--fork-url", rpc_url,
                    "--broadcast",
                    "--sender", "0x0000000000000000000000000000000000000001"
                ]

                if config.private_key:
                    cmd.extend(["--private-key", config.private_key])

                if config.gas_limit:
                    cmd.extend(["--gas-limit", str(config.gas_limit)])

                if config.gas_price:
                    cmd.extend(["--gas-price", str(config.gas_price)])

                # Exécution du script
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=temp_dir
                )

                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=120
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                    self._logger.log_error(
                        "Deployment timed out (120s)",
                        None,
                        "deployment_timeout"
                    )
                    return DeploymentResult(
                        errors=["Deployment timed out"],
                        network=config.network.value,
                        deployment_time=(datetime.now(timezone.utc) - start_time).total_seconds()
                    )

                output = stdout.decode('utf-8', errors='ignore')
                stderr_text = stderr.decode('utf-8', errors='ignore')

                # Extraction de l'adresse du contrat
                contract_address = self._extract_address(output)

                if not contract_address:
                    self._logger.log_error(
                        f"Failed to extract contract address: {output[:500]}",
                        None,
                        "address_extraction_failed"
                    )
                    return DeploymentResult(
                        errors=["Failed to extract contract address"],
                        network=config.network.value,
                        deployment_time=(datetime.now(timezone.utc) - start_time).total_seconds()
                    )

                # Extraction du hash de transaction
                tx_hash = self._extract_transaction_hash(output)

                # Extraction du gas utilisé
                gas_used = self._extract_gas_used(output)

                return DeploymentResult(
                    contract_address=contract_address,
                    transaction_hash=tx_hash,
                    gas_used=gas_used,
                    network=config.network.value,
                    deployment_time=(datetime.now(timezone.utc) - start_time).total_seconds()
                )

            finally:
                # Nettoyage
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)

        except Exception as e:
            self._logger.log_error(
                f"Deployment execution failed: {str(e)}",
                e,
                "deployment_execution_failed"
            )
            return DeploymentResult(
                errors=[str(e)],
                network=config.network.value,
                deployment_time=(datetime.now(timezone.utc) - start_time).total_seconds()
            )

    # =========================================================================
    # VÉRIFICATION DU CONTRAT
    # =========================================================================

    async def _verify_contract(
        self,
        contract_name: str,
        contract_path: str,
        contract_address: str,
        network: Network
    ) -> bool:
        """
        Vérifie le contrat sur Etherscan.

        Args:
            contract_name: Nom du contrat
            contract_path: Chemin du contrat
            contract_address: Adresse du contrat
            network: Réseau de déploiement

        Returns:
            bool: Vérification réussie
        """
        self._logger.log_info(
            f"Verifying contract {contract_name} at {contract_address}",
            "verification_start",
            network=network.value
        )

        try:
            # Construction de la commande Cast
            cmd = [
                self.cast_path,
                "verify",
                "--address", contract_address,
                "--contract", contract_path,
                "--chain", network.value,
                "--etherscan-api-key", "YOUR_API_KEY"  # À configurer
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=60
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                self._logger.log_warning("Verification timed out", "verification_timeout")
                return False

            output = stdout.decode('utf-8', errors='ignore')
            success = "Success" in output or "success" in output.lower()

            self._logger.log_info(
                f"Verification {'successful' if success else 'failed'}",
                "verification_completed",
                success=success
            )

            return success

        except Exception as e:
            self._logger.log_warning(f"Verification failed: {str(e)}", "verification_failed")
            return False

    # =========================================================================
    # UTILITAIRES D'EXTRACTION
    # =========================================================================

    def _extract_address(self, output: str) -> Optional[str]:
        """
        Extrait l'adresse du contrat déployé.

        Args:
            output: Sortie du script

        Returns:
            Optional[str]: Adresse du contrat
        """
        # Recherche de l'adresse
        patterns = [
            r"deployed at: (0x[a-fA-F0-9]{40})",
            r"contract address: (0x[a-fA-F0-9]{40})",
            r"Deployed to: (0x[a-fA-F0-9]{40})",
            r"0x[a-fA-F0-9]{40}"
        ]

        for pattern in patterns:
            match = re.search(pattern, output)
            if match:
                return match.group(1) if '(' in pattern else match.group(0)

        return None

    def _extract_transaction_hash(self, output: str) -> Optional[str]:
        """
        Extrait le hash de transaction.

        Args:
            output: Sortie du script

        Returns:
            Optional[str]: Hash de transaction
        """
        patterns = [
            r"Transaction: (0x[a-fA-F0-9]{64})",
            r"tx: (0x[a-fA-F0-9]{64})",
            r"0x[a-fA-F0-9]{64}"
        ]

        for pattern in patterns:
            match = re.search(pattern, output)
            if match:
                return match.group(1) if '(' in pattern else match.group(0)

        return None

    def _extract_gas_used(self, output: str) -> Optional[int]:
        """
        Extrait le gaz utilisé.

        Args:
            output: Sortie du script

        Returns:
            Optional[int]: Gaz utilisé
        """
        pattern = r"gas used: (\d+)"
        match = re.search(pattern, output)
        if match:
            return int(match.group(1))

        return None

    def _get_rpc_url(self, network: Network) -> str:
        """
        Retourne l'URL RPC pour le réseau donné.

        Args:
            network: Réseau

        Returns:
            str: URL RPC
        """
        rpc_urls = {
            Network.MAINNET: "https://mainnet.infura.io/v3/YOUR_PROJECT_ID",
            Network.SEPOLIA: "https://sepolia.infura.io/v3/YOUR_PROJECT_ID",
            Network.POLYGON: "https://polygon-rpc.com",
            Network.ARBITRUM: "https://arb1.arbitrum.io/rpc",
            Network.OPTIMISM: "https://mainnet.optimism.io",
            Network.BASE: "https://mainnet.base.org",
            Network.AVALANCHE: "https://api.avax.network/ext/bc/C/rpc",
            Network.BSC: "https://bsc-dataseed.binance.org",
            Network.FANTOM: "https://rpc.ftm.tools",
            Network.LOCAL: "http://localhost:8545"
        }

        return rpc_urls.get(network, rpc_urls[Network.LOCAL])

    # =========================================================================
    # STATISTIQUES ET RAPPORTS
    # =========================================================================

    def get_statistics(self) -> Dict[str, Any]:
        """
        Retourne les statistiques de l'agent.

        Returns:
            Dict: Statistiques detaillees
        """
        total_deployments = len(self._deployment_history)
        successful = sum(1 for d in self._deployment_history if d.errors)

        by_network = {}
        for d in self._deployment_history:
            network = d.network or "unknown"
            by_network[network] = by_network.get(network, 0) + 1

        cache_metrics = self._cache.get_metrics()

        return {
            "total_deployments": total_deployments,
            "successful": successful,
            "failed": total_deployments - successful,
            "success_rate": successful / total_deployments if total_deployments > 0 else 0,
            "by_network": by_network,
            "default_network": self.default_network.value,
            "safe_threshold": self.safe_threshold,
            "cache_metrics": cache_metrics
        }

    def get_last_deployment(self) -> Optional[DeploymentResult]:
        """
        Recupere le dernier déploiement.

        Returns:
            Optional[DeploymentResult]: Dernier déploiement
        """
        return self._deployment_history[-1] if self._deployment_history else None

    # =========================================================================
    # REPRESENTATION
    # =========================================================================

    def __repr__(self) -> str:
        return f"<DeployerAgent(agent_id='{self.agent_id}', deployments={len(self._deployment_history)})>"

    def to_dict(self) -> Dict:
        """
        Convertit l'agent en dictionnaire.

        Returns:
            Dict: Representation de l'agent
        """
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "type": "DeployerAgent",
            "default_network": self.default_network.value,
            "deployments_count": len(self._deployment_history),
            "skills_count": len(self.skills),
            "safe_threshold": self.safe_threshold,
            "cache_metrics": self._cache.get_metrics(),
            "health": self.health_check()
        }


# ==============================================================================
# TEST UNITAIRE (si exécuté directement)
# ==============================================================================

if __name__ == "__main__":
    import asyncio

    async def test_deployer():
        print("=" * 60)
        print("Smart Contract Dev Pipeline 2.0 - Deployer Agent")
        print("=" * 60)

        # Création de l'agent
        agent = DeployerAgent(
            agent_id="deployer_001",
            name="TestDeployer",
            default_network=Network.LOCAL
        )

        # Test de déploiement
        print("\n📋 Test de déploiement:")
        result = await agent.execute_task({
            "task_id": "deploy_001",
            "contract_path": "contracts/Counter.sol",
            "contract_name": "Counter",
            "network": "local",
            "constructor_args": {},
            "verify": False
        })

        print(f"  Status: {result.get('status')}")
        print(f"  Contract Address: {result.get('contract_address')}")
        print(f"  Transaction Hash: {result.get('transaction_hash')}")
        print(f"  Network: {result.get('network')}")

        # Statistiques
        print("\n📋 Statistiques:")
        stats = agent.get_statistics()
        for key, value in stats.items():
            if key == "cache_metrics":
                print(f"  {key}: {value}")
            else:
                print(f"  {key}: {value}")

        print("\n✅ Tests terminés.")

    asyncio.run(test_deployer())