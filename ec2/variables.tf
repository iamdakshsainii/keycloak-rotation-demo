variable "aws_region" {
  type    = string
  default = "eu-north-1"
}

variable "your_ip" {   // SG
  description = "Your current public IP for SSH access. Find it at https://checkip.amazonaws.com"
  type        = string
}