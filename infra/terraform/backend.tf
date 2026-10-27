# backend.tf - Estado remoto compartido por el equipo (apartado 4.3, Anexo G.1).
# La cuenta de almacenamiento del estado se crea una sola vez, fuera de este código,
# con bootstrap/crear_backend.sh: el estado no puede depender del propio estado.
terraform {
  required_version = ">= 1.6.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.81"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  backend "azurerm" {
    resource_group_name  = "rg-licita-tfstate"
    storage_account_name = "stlicitatfstate"
    container_name       = "tfstate"
    # La clave se pasa por entorno:
    # terraform init -backend-config="key=licita-dev.tfstate"
  }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy = false
    }
  }
  subscription_id = var.subscription_id
}
