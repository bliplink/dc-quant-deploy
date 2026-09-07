[CmdletBinding()]
param(
    [string]$CommonLibrarySource = "E:\sourcecode\dc\com.app.common",
    [string]$DcCommonSource = (Join-Path $PSScriptRoot "..\com.app.dc"),
    [string]$OrderSvrSource = (Join-Path $PSScriptRoot "..\ordersvr"),
    [string]$GatewayLibrarySource = (Join-Path $PSScriptRoot "..\gateway\gateway"),
    [string]$GatewayImageSource = (Join-Path $PSScriptRoot "..\gw-image"),
    [string]$MavenRepository = (Join-Path $PSScriptRoot ".cluster-dev\m2"),
    [string]$MavenExecutable = "D:\IntelliJ IDEA 2025.3.3\plugins\maven\lib\maven3\bin\mvn.cmd",
    [string]$ImageRepository = "dc-saas/ordersvr",
    [string]$GatewayImageRepository = "dc-saas/gw",
    [switch]$IncludeGateway,
    [switch]$SkipTests,
    [switch]$SkipMavenBuild,
    [switch]$SkipDockerBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host "[cluster-dev] $Message"
}

function Assert-Path([string]$Path, [string]$Description) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Description does not exist: $Path"
    }
}

function Get-PomCoordinate([string]$ProjectPath) {
    $pomPath = Join-Path $ProjectPath "pom.xml"
    Assert-Path $pomPath "Maven POM"
    [xml]$pom = Get-Content -LiteralPath $pomPath -Raw
    $project = $pom.project
    $groupId = [string]$project.groupId
    if ([string]::IsNullOrWhiteSpace($groupId)) {
        $groupId = [string]$project.parent.groupId
    }
    [pscustomobject]@{
        GroupId = $groupId.Trim()
        ArtifactId = ([string]$project.artifactId).Trim()
        Version = ([string]$project.version).Trim()
    }
}

function Get-DependencyVersion([string]$ProjectPath, [string]$GroupId, [string]$ArtifactId) {
    [xml]$pom = Get-Content -LiteralPath (Join-Path $ProjectPath "pom.xml") -Raw
    $dependency = @($pom.project.dependencies.dependency) | Where-Object {
        ([string]$_.groupId).Trim() -eq $GroupId -and ([string]$_.artifactId).Trim() -eq $ArtifactId
    } | Select-Object -First 1
    if ($null -eq $dependency) {
        throw "$ProjectPath does not depend on ${GroupId}:${ArtifactId}"
    }
    return ([string]$dependency.version).Trim()
}

function Get-GitRevision([string]$ProjectPath) {
    $revision = (& git -C $ProjectPath rev-parse --short=12 HEAD 2>$null)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($revision)) {
        throw "Cannot read Git revision from $ProjectPath"
    }
    return $revision.Trim()
}

function Invoke-Maven([string]$ProjectPath, [string[]]$Goals) {
    $arguments = @(
        "-B",
        "-Dmaven.repo.local=$MavenRepository"
    ) + $Goals
    Write-Step "Maven $ProjectPath -> $($Goals -join ' ')"
    & $MavenExecutable -f (Join-Path $ProjectPath "pom.xml") @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Maven failed for $ProjectPath"
    }
}

Assert-Path $MavenExecutable "Maven executable"
Assert-Path $CommonLibrarySource "com.app.common source"
Assert-Path $DcCommonSource "com.app.dc source"
Assert-Path $OrderSvrSource "OrderSvr source"
if ($IncludeGateway) {
    Assert-Path $GatewayLibrarySource "gateway library source"
    Assert-Path $GatewayImageSource "GW image source"
}
if (-not $SkipDockerBuild -and $null -eq (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI is required unless -SkipDockerBuild is specified"
}

$commonCoordinate = Get-PomCoordinate $CommonLibrarySource
$dcCoordinate = Get-PomCoordinate $DcCommonSource
$orderCoordinate = Get-PomCoordinate $OrderSvrSource
$commonGav = "$($commonCoordinate.GroupId):$($commonCoordinate.ArtifactId):$($commonCoordinate.Version)"
$dcGav = "$($dcCoordinate.GroupId):$($dcCoordinate.ArtifactId):$($dcCoordinate.Version)"

$dcCommonVersion = Get-DependencyVersion $DcCommonSource $commonCoordinate.GroupId $commonCoordinate.ArtifactId
if ($dcCommonVersion -ne $commonCoordinate.Version) {
    throw "GAV mismatch: com.app.dc requests $dcCommonVersion but local com.app.common is $($commonCoordinate.Version)"
}
$orderDcVersion = Get-DependencyVersion $OrderSvrSource $dcCoordinate.GroupId $dcCoordinate.ArtifactId
if ($orderDcVersion -ne $dcCoordinate.Version) {
    throw "GAV mismatch: OrderSvr requests $orderDcVersion but local com.app.dc is $($dcCoordinate.Version)"
}

$commonRevision = Get-GitRevision $CommonLibrarySource
$dcRevision = Get-GitRevision $DcCommonSource
$orderRevision = Get-GitRevision $OrderSvrSource
$imageTag = "cluster-dev-$orderRevision-common-$commonRevision"
$imageRef = "${ImageRepository}:$imageTag"
$buildDate = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")

New-Item -ItemType Directory -Force -Path $MavenRepository | Out-Null
Write-Step "Isolated Maven repository: $MavenRepository"
Write-Step "Common: $commonGav @ $commonRevision"
Write-Step "DC common: $dcGav @ $dcRevision"
Write-Step "OrderSvr: $($orderCoordinate.GroupId):$($orderCoordinate.ArtifactId):$($orderCoordinate.Version) @ $orderRevision"

$testArgument = if ($SkipTests) { "-Dmaven.test.skip=true" } else { "-DskipTests=false" }
if (-not $SkipMavenBuild) {
    Invoke-Maven $CommonLibrarySource @("clean", "install", $testArgument)
    Invoke-Maven $DcCommonSource @("clean", "install", $testArgument)
    Invoke-Maven $OrderSvrSource @(
        "clean",
        "package",
        "dependency:copy-dependencies",
        "-DoutputDirectory=target/dependency",
        $testArgument
    )
    if ($IncludeGateway) {
        $gatewayCoordinate = Get-PomCoordinate $GatewayLibrarySource
        $gatewayCommonVersion = Get-DependencyVersion $GatewayLibrarySource $commonCoordinate.GroupId $commonCoordinate.ArtifactId
        if ($gatewayCommonVersion -ne $commonCoordinate.Version) {
            throw "GAV mismatch: gateway requests $gatewayCommonVersion but local com.app.common is $($commonCoordinate.Version)"
        }
        Invoke-Maven $GatewayLibrarySource @("clean", "install", $testArgument)
        Invoke-Maven $GatewayImageSource @(
            "clean",
            "package",
            "dependency:copy-dependencies",
            "-DoutputDirectory=target/dependency",
            "-Dgateway.version=$($gatewayCoordinate.Version)",
            $testArgument
        )
    }
} else {
    Write-Step "Reusing existing Maven outputs; dependency identity checks remain enabled"
}

$dependencyDirectory = Join-Path $OrderSvrSource "target\dependency"
$commonJars = @(Get-ChildItem -LiteralPath $dependencyDirectory -File -Filter "$($commonCoordinate.ArtifactId)-*.jar")
if ($commonJars.Count -ne 1) {
    throw "Expected exactly one $($commonCoordinate.ArtifactId) JAR in $dependencyDirectory, found $($commonJars.Count)"
}
$dcJars = @(Get-ChildItem -LiteralPath $dependencyDirectory -File -Filter "$($dcCoordinate.ArtifactId)-*.jar")
if ($dcJars.Count -ne 1) {
    throw "Expected exactly one $($dcCoordinate.ArtifactId) JAR in $dependencyDirectory, found $($dcJars.Count)"
}

$commonJarHash = (Get-FileHash -LiteralPath $commonJars[0].FullName -Algorithm SHA256).Hash.ToLowerInvariant()
$dcJarHash = (Get-FileHash -LiteralPath $dcJars[0].FullName -Algorithm SHA256).Hash.ToLowerInvariant()

if (-not $SkipDockerBuild) {
    Write-Step "Building immutable development image $imageRef"
    & docker build `
        --build-arg "REPO_URL=https://github.com/bliplink/com.app.dc.ordersvr" `
        --build-arg "SERVICE_REVISION=$orderRevision" `
        --build-arg "COMMON_REVISION=$commonRevision" `
        --build-arg "COMMON_GAV=$commonGav" `
        --build-arg "BUILD_DATE=$buildDate" `
        --label "dc.common.jar.sha256=$commonJarHash" `
        --label "dc.dc-common.revision=$dcRevision" `
        --label "dc.dc-common.jar.sha256=$dcJarHash" `
        --tag $imageRef `
        $OrderSvrSource
    if ($LASTEXITCODE -ne 0) {
        throw "Docker build failed for $imageRef"
    }
}

$manifestDirectory = Join-Path $PSScriptRoot ".cluster-dev"
New-Item -ItemType Directory -Force -Path $manifestDirectory | Out-Null
$manifest = [ordered]@{
    builtAtUtc = $buildDate
    image = $imageRef
    dockerBuildSkipped = [bool]$SkipDockerBuild
    common = [ordered]@{
        gav = $commonGav
        revision = $commonRevision
        jar = $commonJars[0].Name
        sha256 = $commonJarHash
    }
    dcCommon = [ordered]@{
        gav = $dcGav
        revision = $dcRevision
        jar = $dcJars[0].Name
        sha256 = $dcJarHash
    }
    orderSvr = [ordered]@{
        gav = "$($orderCoordinate.GroupId):$($orderCoordinate.ArtifactId):$($orderCoordinate.Version)"
        revision = $orderRevision
    }
}
$manifestPath = Join-Path $manifestDirectory "ordersvr-build-manifest.json"
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Step "Build manifest: $manifestPath"
Write-Step "Image: $imageRef"
Write-Step "Common JAR SHA-256: $commonJarHash"

if ($IncludeGateway) {
    $gatewayCoordinate = Get-PomCoordinate $GatewayLibrarySource
    $gatewayRevision = Get-GitRevision $GatewayLibrarySource
    $gatewayImageRevision = Get-GitRevision $GatewayImageSource
    $gatewayDependencyDirectory = Join-Path $GatewayImageSource "target\dependency"
    $gatewayCommonJars = @(Get-ChildItem -LiteralPath $gatewayDependencyDirectory -File -Filter "$($commonCoordinate.ArtifactId)-*.jar")
    $gatewayLibraryJars = @(Get-ChildItem -LiteralPath $gatewayDependencyDirectory -File -Filter "$($gatewayCoordinate.ArtifactId)-*.jar")
    if ($gatewayCommonJars.Count -ne 1) {
        throw "Expected exactly one $($commonCoordinate.ArtifactId) JAR in $gatewayDependencyDirectory, found $($gatewayCommonJars.Count)"
    }
    if ($gatewayLibraryJars.Count -ne 1) {
        throw "Expected exactly one $($gatewayCoordinate.ArtifactId) JAR in $gatewayDependencyDirectory, found $($gatewayLibraryJars.Count)"
    }
    $gatewayCommonJarHash = (Get-FileHash -LiteralPath $gatewayCommonJars[0].FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($gatewayCommonJarHash -ne $commonJarHash) {
        throw "GW and OrderSvr contain different com.app.common JARs"
    }
    $gatewayLibraryJarHash = (Get-FileHash -LiteralPath $gatewayLibraryJars[0].FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    $gatewayImageRef = "${GatewayImageRepository}:cluster-dev-$gatewayImageRevision-gateway-$gatewayRevision-common-$commonRevision"
    if (-not $SkipDockerBuild) {
        Write-Step "Building immutable development image $gatewayImageRef"
        & docker build `
            --build-arg "REPO_URL=https://github.com/bliplink/gw" `
            --build-arg "SERVICE_REVISION=$gatewayImageRevision" `
            --build-arg "GATEWAY_REVISION=$gatewayRevision" `
            --build-arg "COMMON_REVISION=$commonRevision" `
            --build-arg "COMMON_GAV=$commonGav" `
            --build-arg "BUILD_DATE=$buildDate" `
            --label "dc.common.jar.sha256=$gatewayCommonJarHash" `
            --label "dc.gateway.jar.sha256=$gatewayLibraryJarHash" `
            --tag $gatewayImageRef `
            $GatewayImageSource
        if ($LASTEXITCODE -ne 0) {
            throw "Docker build failed for $gatewayImageRef"
        }
    }
    $gatewayManifest = [ordered]@{
        builtAtUtc = $buildDate
        image = $gatewayImageRef
        dockerBuildSkipped = [bool]$SkipDockerBuild
        common = [ordered]@{
            gav = $commonGav
            revision = $commonRevision
            jar = $gatewayCommonJars[0].Name
            sha256 = $gatewayCommonJarHash
        }
        gateway = [ordered]@{
            gav = "$($gatewayCoordinate.GroupId):$($gatewayCoordinate.ArtifactId):$($gatewayCoordinate.Version)"
            revision = $gatewayRevision
            jar = $gatewayLibraryJars[0].Name
            sha256 = $gatewayLibraryJarHash
        }
        wrapperRevision = $gatewayImageRevision
    }
    $gatewayManifestPath = Join-Path $manifestDirectory "gw-build-manifest.json"
    $gatewayManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $gatewayManifestPath -Encoding UTF8
    Write-Step "GW build manifest: $gatewayManifestPath"
    Write-Step "GW image: $gatewayImageRef"
}
