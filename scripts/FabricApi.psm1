# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT

# FabricApi.psm1
# Purpose: Shared Microsoft Entra authentication and Fabric REST helpers.

#Requires -Version 7.0

$script:FabricApiBaseUri = 'https://api.fabric.microsoft.com/v1'

function Get-FabricAccessToken {
    <#
    .SYNOPSIS
        Acquires a Fabric token using explicit federation, a client secret, or GitHub OIDC.
    .OUTPUTS
        System.String access token.
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param()

    $RequiredNames = @('AZURE_CLIENT_ID', 'AZURE_TENANT_ID')
    $MissingNames = @(
        $RequiredNames | Where-Object {
            -not (Test-Path "env:$_") -or
                [string]::IsNullOrWhiteSpace((Get-Item "env:$_").Value)
        }
    )
    if ($MissingNames.Count -gt 0) {
        throw "Missing environment variables: $($MissingNames -join ', ')"
    }

    $FederatedToken = $null
    if (-not [string]::IsNullOrWhiteSpace($env:AZURE_FEDERATED_TOKEN)) {
        $FederatedToken = $env:AZURE_FEDERATED_TOKEN
    }
    elseif (
        -not [string]::IsNullOrWhiteSpace($env:AZURE_FEDERATED_TOKEN_FILE) -and
        (Test-Path -LiteralPath $env:AZURE_FEDERATED_TOKEN_FILE)
    ) {
        $FederatedToken = (Get-Content -LiteralPath $env:AZURE_FEDERATED_TOKEN_FILE -Raw).Trim()
    }
    elseif (
        [string]::IsNullOrWhiteSpace($env:AZURE_CLIENT_SECRET) -and
        -not [string]::IsNullOrWhiteSpace($env:ACTIONS_ID_TOKEN_REQUEST_URL) -and
        -not [string]::IsNullOrWhiteSpace($env:ACTIONS_ID_TOKEN_REQUEST_TOKEN)
    ) {
        $Separator = if ($env:ACTIONS_ID_TOKEN_REQUEST_URL.Contains('?')) { '&' } else { '?' }
        $OidcUri = "$($env:ACTIONS_ID_TOKEN_REQUEST_URL)${Separator}audience=api://AzureADTokenExchange"
        $OidcHeaders = @{ Authorization = ('Bearer ' + $env:ACTIONS_ID_TOKEN_REQUEST_TOKEN) }
        $OidcResponse = Invoke-RestMethod -Method Get -Uri $OidcUri -Headers $OidcHeaders
        $FederatedToken = [string]$OidcResponse.value
    }

    $TokenBody = @{
        client_id  = $env:AZURE_CLIENT_ID
        scope      = 'https://api.fabric.microsoft.com/.default'
        grant_type = 'client_credentials'
    }
    if (-not [string]::IsNullOrWhiteSpace($FederatedToken)) {
        $TokenBody['client_assertion_type'] = 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer'
        $TokenBody['client_assertion'] = $FederatedToken
    }
    elseif (-not [string]::IsNullOrWhiteSpace($env:AZURE_CLIENT_SECRET)) {
        $TokenBody['client_secret'] = $env:AZURE_CLIENT_SECRET
    }
    else {
        throw 'Configure Entra OIDC federation (GitHub Actions id-token, AZURE_FEDERATED_TOKEN_FILE, or AZURE_FEDERATED_TOKEN) or AZURE_CLIENT_SECRET.'
    }

    $Response = Invoke-RestMethod -Method Post `
        -Uri "https://login.microsoftonline.com/$env:AZURE_TENANT_ID/oauth2/v2.0/token" `
        -ContentType 'application/x-www-form-urlencoded' `
        -Body $TokenBody
    return [string]$Response.access_token
}

function Invoke-FabricRequest {
    <#
    .SYNOPSIS
        Calls Fabric REST with telemetry and bounded long-running-operation polling.
    .OUTPUTS
        Parsed JSON response or null.
    #>
    [CmdletBinding()]
    [OutputType([object])]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet('Get', 'Post', 'Patch')]
        [string]$Method,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Uri,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Token,

        [Parameter(Mandatory = $true)]
        [ValidatePattern('^[a-z0-9-]+$')]
        [string]$SkillName,

        [Parameter(Mandatory = $false)]
        [string]$Body,

        [Parameter(Mandatory = $false)]
        [switch]$FetchResult
    )

    $Headers = @{
        Authorization       = "Bearer $Token"
        'x-ms-fabric-skill' = $SkillName
    }
    if ($PSBoundParameters.ContainsKey('Body')) {
        $Headers['Content-Type'] = 'application/json'
    }
    elseif ($Method -eq 'Post') {
        $Headers['Content-Length'] = '0'
    }

    $Arguments = @{
        Method             = $Method
        Uri                = $Uri
        Headers            = $Headers
        SkipHttpErrorCheck = $true
        MaximumRedirection = 0
    }
    if ($PSBoundParameters.ContainsKey('Body')) {
        $Arguments.Body = $Body
    }
    $Response = $null
    for ($RequestAttempt = 0; $RequestAttempt -lt 6; $RequestAttempt++) {
        $Response = Invoke-WebRequest @Arguments
        if ($Response.StatusCode -notin @(429, 503)) {
            break
        }
        if ($RequestAttempt -eq 5) {
            break
        }
        $ThrottleText = [string](
            $Response.Headers.'Retry-After' | Select-Object -First 1
        )
        $ThrottleDelay = if (
            $ThrottleText -match '^\d+$' -and [int]$ThrottleText -gt 0
        ) {
            [int]$ThrottleText
        }
        else {
            5
        }
        Start-Sleep -Seconds $ThrottleDelay
    }
    if ($Response.StatusCode -lt 200 -or $Response.StatusCode -ge 300) {
        throw "Fabric request failed ($($Response.StatusCode)): $($Response.Content)"
    }

    if ($Response.StatusCode -eq 202) {
        $Location = [string]($Response.Headers.Location | Select-Object -First 1)
        $OperationId = [string](
            $Response.Headers.'x-ms-operation-id' | Select-Object -First 1
        )
        if (-not [string]::IsNullOrWhiteSpace($Location)) {
            $OperationUri = [Uri]::new(
                [Uri]'https://api.fabric.microsoft.com',
                $Location
            ).AbsoluteUri
        }
        elseif (-not [string]::IsNullOrWhiteSpace($OperationId)) {
            $OperationUri = "$script:FabricApiBaseUri/operations/$OperationId"
        }
        else {
            throw 'Fabric returned 202 without a Location or x-ms-operation-id header'
        }

        $RetryText = [string](
            $Response.Headers.'Retry-After' | Select-Object -First 1
        )
        $RetryAfter = if ($RetryText -match '^\d+$' -and [int]$RetryText -gt 0) {
            [int]$RetryText
        }
        else {
            5
        }
        $Operation = $null
        for ($Attempt = 0; $Attempt -lt 120; $Attempt++) {
            Start-Sleep -Seconds $RetryAfter
            $Operation = Invoke-FabricRequest -Method Get -Uri $OperationUri `
                -Token $Token -SkillName $SkillName
            if ($Operation.status -in @('Succeeded', 'Completed')) {
                break
            }
            if ($Operation.status -in @('Failed', 'Cancelled', 'Deduped')) {
                throw "Fabric operation ended in $($Operation.status): $($Operation | ConvertTo-Json -Depth 20 -Compress)"
            }
        }
        if ($Operation.status -notin @('Succeeded', 'Completed')) {
            throw "Fabric operation timed out in status '$($Operation.status)'"
        }
        if ($FetchResult -and $Operation.status -eq 'Succeeded') {
            return Invoke-FabricRequest -Method Get -Uri "$OperationUri/result" `
                -Token $Token -SkillName $SkillName
        }
        return $Operation
    }

    if ([string]::IsNullOrWhiteSpace($Response.Content)) {
        return $null
    }
    return $Response.Content | ConvertFrom-Json
}

Export-ModuleMember -Function @(
    'Get-FabricAccessToken'
    'Invoke-FabricRequest'
)
