<#
One-time GCP setup for a single environment (dev or prod). Idempotent.
Run once per project from Windows PowerShell (requires gcloud):

    .\scripts\bootstrap.ps1 dev
    .\scripts\bootstrap.ps1 prod

Reads config/<env>.env for PROJECT_ID, REGION, etc.
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('dev', 'prod')]
    [string]$EnvName
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$conf = Join-Path $root "config\$EnvName.env"
if (-not (Test-Path $conf)) { throw "Missing $conf" }

# Parse KEY=VALUE lines into a hashtable.
$cfg = @{}
Get-Content $conf | Where-Object { $_ -match '^\s*[^#].*=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2
    $cfg[$k.Trim()] = $v.Trim()
}

$projectId  = $cfg['PROJECT_ID']
$region     = $cfg['REGION']
$arRepo     = $cfg['AR_REPO']
$secret     = $cfg['API_KEY_SECRET']
$gcs        = $cfg['GCS_SOURCE']
$bucket     = ($gcs -replace '^gs://', '') -replace '/.*$', ''
$runtimeSa  = "rag-agent-runtime@$projectId.iam.gserviceaccount.com"
$ciSa       = "rag-agent-ci@$projectId.iam.gserviceaccount.com"

Write-Host "== Project: $projectId (env=$EnvName, region=$region)"
gcloud config set project $projectId | Out-Null

Write-Host "== Enabling APIs"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com `
    artifactregistry.googleapis.com aiplatform.googleapis.com `
    secretmanager.googleapis.com storage.googleapis.com `
    firestore.googleapis.com

Write-Host "== Artifact Registry repo: $arRepo"
$ErrorActionPreference = 'Continue'
gcloud artifacts repositories describe $arRepo --location=$region 2>$null | Out-Null
$repoExists = $?
$ErrorActionPreference = 'Stop'
if (-not $repoExists) {
    gcloud artifacts repositories create $arRepo --repository-format=docker `
        --location=$region --description="RAG agent images"
}

Write-Host "== GCS corpus bucket: gs://$bucket"
$ErrorActionPreference = 'Continue'
gcloud storage buckets describe "gs://$bucket" 2>$null | Out-Null
$bucketExists = $?
$ErrorActionPreference = 'Stop'
if (-not $bucketExists) {
    gcloud storage buckets create "gs://$bucket" --location=$region --uniform-bucket-level-access
}

Write-Host "== Runtime service account: $runtimeSa"
$ErrorActionPreference = 'Continue'
gcloud iam service-accounts describe $runtimeSa 2>$null | Out-Null
$runtimeSaExists = $?
$ErrorActionPreference = 'Stop'
if (-not $runtimeSaExists) { gcloud iam service-accounts create rag-agent-runtime --display-name="RAG agent runtime" }
foreach ($role in @('roles/aiplatform.user', 'roles/storage.objectViewer', 'roles/secretmanager.secretAccessor', 'roles/datastore.user')) {
    gcloud projects add-iam-policy-binding $projectId --member="serviceAccount:$runtimeSa" --role=$role --condition=None | Out-Null
}

Write-Host "== CI service account: $ciSa"
$ErrorActionPreference = 'Continue'
gcloud iam service-accounts describe $ciSa 2>$null | Out-Null
$ciSaExists = $?
$ErrorActionPreference = 'Stop'
if (-not $ciSaExists) { gcloud iam service-accounts create rag-agent-ci --display-name="RAG agent CI/CD" }
foreach ($role in @('roles/run.admin', 'roles/artifactregistry.writer', 'roles/aiplatform.user', 'roles/storage.admin', 'roles/logging.logWriter')) {
    gcloud projects add-iam-policy-binding $projectId --member="serviceAccount:$ciSa" --role=$role --condition=None | Out-Null
}
gcloud iam service-accounts add-iam-policy-binding $runtimeSa --member="serviceAccount:$ciSa" --role="roles/iam.serviceAccountUser" | Out-Null

Write-Host "== API key secret: $secret"
$ErrorActionPreference = 'Continue'
gcloud secrets describe $secret 2>$null | Out-Null
$secretExists = $?
$ErrorActionPreference = 'Stop'
if (-not $secretExists) {
    gcloud secrets create $secret --replication-policy=automatic
    Write-Host "  -> Add a value: 'YOUR_KEY' | gcloud secrets versions add $secret --data-file=- --project=$projectId"
}

Write-Host ""
Write-Host "== Done for $projectId."
Write-Host "Next: add the API key secret value, upload docs to gs://$bucket/, connect the repo,"
Write-Host "      and create the Cloud Build trigger with service account: $ciSa"
