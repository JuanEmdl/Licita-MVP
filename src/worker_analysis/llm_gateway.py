import os
from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel
from typing import Any

# DA-07: Pasarela única hacia el proveedor del modelo
# Concentra anonimización, control de cuota, reintentos, disyuntor y telemetría.

class LLMGateway:
    def __init__(self):
        # In a real scenario, this would read from Azure OpenAI env vars
        self.api_key = os.getenv("AZURE_OPENAI_API_KEY", "mock-key")
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "https://mock.openai.azure.com/")
        
        # We configure the base LLM with retries (reintentos con espera exponencial)
        self.llm = ChatOpenAI(
            model="gpt-4o", # Reference model
            api_key=self.api_key,
            base_url=self.endpoint,
            max_retries=3,
            temperature=0.0 # Deterministic behavior where possible
        )

    def _anonymize(self, text: str) -> str:
        # ASR-05: Anonimización antes de toda llamada al proveedor del modelo
        # TODO: Implement robust anonymization logic (e.g., Presidio)
        # Mock implementation:
        return text.replace("NombreFabrica", "[FABRICA_ANONIMA]")

    def _deanonymize(self, text: str) -> str:
        # Restore anonymized entities
        return text.replace("[FABRICA_ANONIMA]", "NombreFabrica")
        
    def _check_quota(self):
        # ASR-13: Techo de consumo de tokens por periodo
        # TODO: Implement quota tracking in Redis/DB
        pass
        
    def _telemetry(self, prompt: str, response: str):
        # RF-043: Telemetría correlacionada por tarea
        # TODO: Export to OpenTelemetry / Azure Monitor
        pass

    def get_structured_llm(self, schema: Any) -> BaseChatModel:
        """
        Returns a model bound to a specific tool/schema to ensure structured output (DA-08).
        Agents do not have tools with side effects; they only produce structured data.
        """
        # Wrapping with with_structured_output guarantees validation against the schema
        return self.llm.with_structured_output(schema)

    def invoke(self, prompt: str) -> str:
        self._check_quota()
        safe_prompt = self._anonymize(prompt)
        
        # Telemetry before
        response = self.llm.invoke(safe_prompt)
        
        # Telemetry after
        final_text = self._deanonymize(response.content)
        self._telemetry(safe_prompt, final_text)
        
        return final_text

    def invoke_structured(self, prompt: str, schema: Any) -> Any:
        self._check_quota()
        safe_prompt = self._anonymize(prompt)
        
        structured_llm = self.get_structured_llm(schema)
        response = structured_llm.invoke(safe_prompt)
        
        # For structured output, deanonymization would require traversing the object.
        # This is simplified for the MVP skeleton.
        self._telemetry(safe_prompt, str(response))
        return response

# Singleton instance of the gateway
pasarela_llm = LLMGateway()
