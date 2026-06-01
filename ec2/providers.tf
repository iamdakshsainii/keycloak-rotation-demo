terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"  // to talk to AWS
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"  // generate ssh key
      version = "~> 4.0"
    }
    local = {
      source  = "hashicorp/local"   // .pem file save to your machine
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}