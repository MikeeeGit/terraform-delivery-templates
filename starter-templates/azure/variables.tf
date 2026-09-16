variable "subscription_id_map" {
  description = "Keep aligned with subscriptions in delivery.azure.json."
  type        = map(string)
}
variable "subscription" {
  description = "Workload subscription alias (dev maps to pprd; shr to hub; bcdr to prd)."
  type        = string
}
variable "environment" {
  description = "Selected environment, matching its tfvars folder."
  type        = string
}
variable "location" {
  description = "Full Azure region name."
  type        = string
}
variable "location_abbreviated" {
  description = "Region abbreviation used in resource names and state keys."
  type        = string
}
variable "company_abbreviation" {
  description = "Synthetic example naming prefix."
  type        = string
}
