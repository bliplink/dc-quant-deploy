[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [switch]$KeepRunning
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$deployRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = Split-Path -Parent $deployRoot
$orderSource = Join-Path $workspaceRoot "ordersvr"
$gatewaySource = Join-Path $workspaceRoot "gw-image"
$commonSource = "E:\sourcecode\dc\com.app.common"
$buildScript = Join-Path $deployRoot "build-cluster-dev-ordersvr.ps1"
$licenseSource = Join-Path $deployRoot "control.prod\dc.dat"

function Write-Step([string]$Message) {
    Write-Host "[order-ab-local] $Message"
}

function Write-Utf8([string]$Path, [string]$Content) {
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    [IO.File]::WriteAllText($Path, $Content, (New-Object Text.UTF8Encoding($false)))
}

function Assert-Port-Free([int]$Port) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if ($null -ne $listener) {
        throw "TCP port $Port is already in use"
    }
}

function Wait-Port([int]$Port, [int]$TimeoutSeconds, [string]$Name) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $client = New-Object Net.Sockets.TcpClient
        try {
            $pending = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
            if ($pending.AsyncWaitHandle.WaitOne(500) -and $client.Connected) {
                $client.EndConnect($pending)
                return
            }
        } catch {
        } finally {
            $client.Dispose()
        }
        Start-Sleep -Milliseconds 250
    }
    throw "$Name did not listen on 127.0.0.1:$Port within $TimeoutSeconds seconds"
}

function Wait-LogPattern([string]$Path, [string]$Pattern, [int]$TimeoutSeconds, [string]$Name) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ((Test-Path -LiteralPath $Path) -and (Select-String -LiteralPath $Path -Pattern $Pattern -Quiet)) {
            return
        }
        Start-Sleep -Milliseconds 250
    }
    throw "$Name was not observed in $Path within $TimeoutSeconds seconds"
}

function Start-JavaProcess(
    [string]$Name,
    [string]$WorkingDirectory,
    [string]$ClassPath,
    [string]$MainClass,
    [string[]]$ExtraArguments,
    [string]$BackendRoot,
    [string]$LogDirectory
) {
    New-Item -ItemType Directory -Force -Path $WorkingDirectory,$LogDirectory | Out-Null
    $stdout = Join-Path $LogDirectory "$Name.stdout.log"
    $stderr = Join-Path $LogDirectory "$Name.stderr.log"
    $log4jPath = (Join-Path $WorkingDirectory "config\log4j.ini").Replace('\','/')
    $arguments = @(
        "-server", "-Xms32m", "-Xmx192m", "-Xmn48m", "-Xss256k",
        "--add-exports=java.base/jdk.internal.ref=ALL-UNNAMED",
        "--add-exports=java.base/sun.nio.ch=ALL-UNNAMED",
        "--add-exports=jdk.unsupported/sun.misc=ALL-UNNAMED",
        "--add-opens=java.base/java.lang=ALL-UNNAMED",
        "--add-opens=java.base/java.lang.reflect=ALL-UNNAMED",
        "--add-opens=java.base/java.io=ALL-UNNAMED",
        "--add-opens=java.base/java.nio=ALL-UNNAMED",
        "--add-opens=java.base/java.util=ALL-UNNAMED",
        "--add-opens=java.base/sun.nio.ch=ALL-UNNAMED",
        "--add-opens=jdk.unsupported/sun.misc=ALL-UNNAMED",
        "-Dlog4j.configuration=file:/$log4jPath", "-cp", $ClassPath, $MainClass
    ) + $ExtraArguments
    $previousBackendRoot = $env:BACKEND_ROOT
    try {
        $env:BACKEND_ROOT = $BackendRoot
        $process = Start-Process -FilePath "java.exe" -ArgumentList $arguments `
            -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    } finally {
        if ($null -eq $previousBackendRoot) {
            Remove-Item Env:BACKEND_ROOT -ErrorAction SilentlyContinue
        } else {
            $env:BACKEND_ROOT = $previousBackendRoot
        }
    }
    Write-Step "Started $Name pid=$($process.Id)"
    return $process
}

function Invoke-GwRequest([string]$RequestPath, [string]$ResponsePath, [int]$MaxSeconds) {
    $curl = Start-Process -FilePath "curl.exe" -ArgumentList @(
        "--silent", "--show-error", "--max-time", "$MaxSeconds",
        "-X", "POST", "-H", "Content-Type:application/json", "--data-binary", "@$RequestPath",
        "http://127.0.0.1:3032"
    ) -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput $ResponsePath `
        -RedirectStandardError "$ResponsePath.stderr"
    return $curl.ExitCode
}

function ServerConfig([string]$Key, [string]$ServiceName, [int]$Port, [int]$RegType = 2) {
    return @"
SERVER.$Key.Name=$ServiceName
SERVER.$Key.Host=127.0.0.1:$Port
SERVER.$Key.RegType=$RegType
SERVER.$Key.RegisterEnable=1
SERVER.$Key.LBFactor=1
SERVER.$Key.ServiceName=$ServiceName
SERVER.$Key.RegisterServerList=REGISTER.Svr1
"@
}

function OrderConfig([string]$Node, [int]$ReplicationPort, [string]$RunRoot) {
    $nodePath = (Join-Path $RunRoot "data\$Node").Replace('\','/')
    return @"
dbType=rockdb
execOrderType=default
orderStorePath=$nodePath/store
serverKey=SERVER.$Node
tradeServerKey=SERVER.TradeSvr

order.cluster.journal.enabled=true
order.cluster.journal.required=true
order.cluster.journalDir=$nodePath/journal
order.cluster.serviceName=SERVER.OrderSvr
order.cluster.state.enabled=false
order.cluster.state.required=false
order.cluster.state.replication.required=false
order.cluster.commit.enabled=false
order.cluster.commit.required=false
order.cluster.snapshot.enabled=false
order.cluster.snapshotDir=$nodePath/snapshot
order.cluster.replication.enabled=true
order.cluster.replication.required=true
order.cluster.replication.bindHost=127.0.0.1
order.cluster.replication.port=$ReplicationPort
order.cluster.replication.requestTimeoutMs=3000
order.cluster.replication.catchupBatchRecords=256
order.cluster.replication.peers=OrderSvrA=127.0.0.1:19101,OrderSvrB=127.0.0.1:19102
order.cluster.defaultMarketIndicator=4

enableMarketPrice=false
enableSaveDBDemo=false
enableDepthDiff=false
enableFullOrderBookOnChange=false
order.selfTradePreventionMode=CANCEL_TAKER
enablePerfStats=false
log4j.file=./config/log4j.ini
log4j.thread=1
log4j.writeTime=true
log4j.async=false
"@
}

$ports = @(32182,3030,3031,3032,33136,33236,19101,19102)
foreach ($port in $ports) { Assert-Port-Free $port }

if (-not $SkipBuild) {
    Write-Step "Building Common, OrderSvr, gateway and GW with the isolated Maven repository"
    & $buildScript -IncludeGateway -SkipDockerBuild
    if ($LASTEXITCODE -ne 0) { throw "cluster development build failed" }
}

$required = @(
    (Join-Path $orderSource "target\classes\OrderSvr.class"),
    (Join-Path $gatewaySource "target\classes\GW.class"),
    (Join-Path $gatewaySource "target\dependency\zookeeper-3.5.9.jar"),
    $licenseSource
)
foreach ($path in $required) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required build output is missing: $path" }
}

$runId = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
$runRoot = Join-Path $deployRoot ".cluster-dev\order-ab-local\$runId"
$backendRoot = Join-Path $runRoot "backend"
$controlRoot = Join-Path $backendRoot "control"
$logRoot = Join-Path $runRoot "logs"
$zkRoot = Join-Path $runRoot "zookeeper"
$orderARoot = Join-Path $runRoot "OrderSvrA"
$orderBRoot = Join-Path $runRoot "OrderSvrB"
$gatewayRoot = Join-Path $runRoot "GW"
New-Item -ItemType Directory -Force -Path $controlRoot,$logRoot,$zkRoot,$orderARoot,$orderBRoot,$gatewayRoot | Out-Null
Copy-Item -LiteralPath $licenseSource -Destination (Join-Path $controlRoot "dc.dat")

$atsConfig = @"
REGISTER.ServerList=REGISTER.Svr1
REGISTER.Svr1.Name=REGISTER1
REGISTER.Svr1.Host=127.0.0.1:32182
NetType=dps
ProtoVersion=1

$(ServerConfig "OrderSvr" "OrderSvr" 33999 0)
$(ServerConfig "OrderSvrA" "OrderSvrA" 33136 0)
$(ServerConfig "OrderSvrB" "OrderSvrB" 33236 0)
$(ServerConfig "LoginSvr" "LoginSvr" 33991)
$(ServerConfig "AdminSvr" "AdminSvr" 33992)
$(ServerConfig "TradeSvr" "TDSvr" 33993)

LBConfig.OrderSvr=Partition
Cluster.Enabled=true
Cluster.OrderSvr.Enabled=true
Cluster.OrderSvrA.Enabled=true
Cluster.OrderSvrB.Enabled=true

Partition.OrderSvr.Count=256
Partition.OrderSvr.Root=/dc/cluster/ordersvr/partitions
Partition.OrderSvr.EnforceFence=true

Partition.OrderSvrA.Count=256
Partition.OrderSvrA.Root=/dc/cluster/ordersvr/partitions
Partition.OrderSvrA.EnforceFence=true
Partition.OrderSvrB.Count=256
Partition.OrderSvrB.Root=/dc/cluster/ordersvr/partitions
Partition.OrderSvrB.EnforceFence=true
"@
Write-Utf8 (Join-Path $controlRoot "ATSConfig.ini") $atsConfig

$log4j = @"
log4j.rootLogger=INFO,stdout
log4j.appender.stdout=org.apache.log4j.ConsoleAppender
log4j.appender.stdout.Target=System.out
log4j.appender.stdout.layout=org.apache.log4j.PatternLayout
log4j.appender.stdout.layout.ConversionPattern=%d{yyyy/MM/dd HH:mm:ss.SSS} %p %m (%C{1}:%L)%n
log4j.logger.com.app.dc.service.cluster.OrderClusterAdapter=DEBUG
log4j.logger.com.gateway.connector.tcp.client.BaseApi=WARN
log4j.logger.io.netty.handler.logging.LoggingHandler=WARN
"@

foreach ($definition in @(
    @{ Root=$orderARoot; Config=(OrderConfig "OrderSvrA" 19101 $runRoot) },
    @{ Root=$orderBRoot; Config=(OrderConfig "OrderSvrB" 19102 $runRoot) }
)) {
    Write-Utf8 (Join-Path $definition.Root "config\application.properties") $definition.Config
    Write-Utf8 (Join-Path $definition.Root "config\log4j.ini") $log4j
}

$springConfig = @"
<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
 xsi:schemaLocation="http://www.springframework.org/schema/beans http://www.springframework.org/schema/beans/spring-beans-3.0.xsd">
 <import resource="spring-tcp-server.xml"/>
 <import resource="spring-gw-client.xml"/>
</beans>
"@
$springClient = @"
<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
 xsi:schemaLocation="http://www.springframework.org/schema/beans http://www.springframework.org/schema/beans/spring-beans-3.0.xsd">
 <bean id="proxy" class="com.gateway.invoke.gw.GWProxy" init-method="init">
  <property name="topicManager" ref="topicManager"/><property name="notifyProxy" ref="notify"/>
  <property name="tcpConnector" ref="tcpConnector"/><property name="SessionService" value=""/>
  <property name="RequestService" value="OrderSvr"/><property name="Subscribes"><map/></property>
  <property name="securityChecks"><list/></property><property name="filterTopics"><list/></property>
  <property name="ApiKeyService" ref="apiKeyService"/>
 </bean>
 <bean id="apiKeyService" class="com.gateway.invoke.filter.apikey.ApiKeyService"/>
</beans>
"@
$springServer = @"
<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
 xsi:schemaLocation="http://www.springframework.org/schema/beans http://www.springframework.org/schema/beans/spring-beans-4.3.xsd">
 <bean id="tcpServer" class="com.gateway.connector.tcp.server.TServer" init-method="init" destroy-method="shutdown"><property name="port" value="3030"/><property name="serverConfig" ref="serverConfig"/></bean>
 <bean id="webSocketServer" class="com.gateway.connector.tcp.server.WebSocketServer" init-method="init" destroy-method="shutdown"><property name="port" value="3031"/><property name="serverConfig" ref="webSocketServerConfig"/></bean>
 <bean id="httpServer" class="com.gateway.connector.tcp.server.HttpServer" init-method="init" destroy-method="shutdown"><property name="port" value="3032"/><property name="serverConfig" ref="serverConfig"/></bean>
 <bean id="tcpSessionManager" class="com.gateway.connector.tcp.TcpSessionManager"><property name="maxInactiveInterval" value="500"/><property name="topicManager" ref="topicManager"/><property name="sessionListeners"><list><ref bean="logSessionListener"/></list></property></bean>
 <bean id="logSessionListener" class="com.gateway.connector.api.listener.LogSessionListener"/>
 <bean id="tcpSender" class="com.gateway.remoting.TcpSender"><property name="tcpConnector" ref="tcpConnector"/></bean>
 <bean id="serverConfig" class="com.gateway.connector.tcp.config.ServerTransportConfig"><property name="tcpConnector" ref="tcpConnector"/><property name="proxy" ref="proxy"/><property name="notify" ref="notify"/><property name="gzip" value="true"/><property name="login" value="false"/></bean>
 <bean id="webSocketServerConfig" class="com.gateway.connector.tcp.config.ServerTransportConfig"><property name="tcpConnector" ref="tcpConnector"/><property name="proxy" ref="proxy"/><property name="notify" ref="notify"/><property name="gzip" value="true"/><property name="login" value="false"/></bean>
 <bean id="tcpConnector" class="com.gateway.connector.tcp.TcpConnector" init-method="init" destroy-method="destroy"><property name="tcpSessionManager" ref="tcpSessionManager"/></bean>
 <bean id="topicManager" class="com.gateway.invoke.TopicManager"/><bean id="notify" class="com.gateway.notify.NotifyProxy"><property name="tcpConnector" ref="tcpConnector"/><property name="topicManager" ref="topicManager"/></bean>
</beans>
"@
Write-Utf8 (Join-Path $gatewayRoot "config\spring-config.xml") $springConfig
Write-Utf8 (Join-Path $gatewayRoot "config\spring-gw-client.xml") $springClient
Write-Utf8 (Join-Path $gatewayRoot "config\spring-tcp-server.xml") $springServer
Write-Utf8 (Join-Path $gatewayRoot "config\log4j.ini") $log4j

$zooData = (Join-Path $zkRoot "data").Replace('\','/')
Write-Utf8 (Join-Path $zkRoot "zoo.cfg") "tickTime=2000`ndataDir=$zooData`nclientPort=32182`nadmin.enableServer=false`n4lw.commands.whitelist=*`n"
Write-Utf8 (Join-Path $zkRoot "config\log4j.ini") $log4j

$orderClassPath = "$(Join-Path $orderSource 'target\classes');$(Join-Path $orderSource 'target\dependency\*')"
$gatewayClassPath = "$(Join-Path $gatewaySource 'target\classes');$(Join-Path $gatewaySource 'target\dependency\*')"
$seedSource = Join-Path $zkRoot "ZkSeeder.java"
$seedClasses = Join-Path $zkRoot "seed-classes"
$seedJava = @'
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.KeeperException;
import org.apache.zookeeper.WatchedEvent;
import org.apache.zookeeper.Watcher;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.ZooKeeper;

public final class ZkSeeder {
    private static void create(ZooKeeper zk, String path, String data) throws Exception {
        try {
            zk.create(path, data.getBytes(StandardCharsets.UTF_8),
                ZooDefs.Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        } catch (KeeperException.NodeExistsException ignored) {
            zk.setData(path, data.getBytes(StandardCharsets.UTF_8), -1);
        }
    }

    public static void main(String[] args) throws Exception {
        CountDownLatch connected = new CountDownLatch(1);
        ZooKeeper zk = new ZooKeeper(args[0], 10000, new Watcher() {
            @Override public void process(WatchedEvent event) {
                if (event.getState() == Event.KeeperState.SyncConnected) connected.countDown();
            }
        });
        try {
            if (!connected.await(10, TimeUnit.SECONDS)) throw new IllegalStateException("ZooKeeper connection timeout");
            create(zk, "/dc", "x");
            create(zk, "/dc/cluster", "x");
            create(zk, "/dc/cluster/ordersvr", "x");
            create(zk, "/dc/cluster/ordersvr/partitions", "x");
            create(zk, "/dc/cluster/ordersvr/partitions/P027", "{\"partitionId\":\"P027\",\"epoch\":1,\"primary\":\"OrderSvrA\",\"replica\":\"OrderSvrB\",\"state\":\"READY\"}");
            create(zk, "/dc/cluster/ordersvr/partitions/P132", "{\"partitionId\":\"P132\",\"epoch\":1,\"primary\":\"OrderSvrB\",\"replica\":\"OrderSvrA\",\"state\":\"READY\"}");
        } finally {
            zk.close();
        }
    }
}
'@
Write-Utf8 $seedSource $seedJava
New-Item -ItemType Directory -Force -Path $seedClasses | Out-Null
$processIds = @()
$testSucceeded = $false

try {
    $zk = Start-JavaProcess "zookeeper" $zkRoot $gatewayClassPath "org.apache.zookeeper.server.quorum.QuorumPeerMain" @((Join-Path $zkRoot "zoo.cfg")) $backendRoot $logRoot
    $processIds += $zk.Id
    Wait-Port 32182 30 "ZooKeeper"

    $compile = Start-Process -FilePath "javac.exe" -ArgumentList @("-cp", $gatewayClassPath, "-d", $seedClasses, $seedSource) `
        -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput (Join-Path $logRoot "zookeeper-seed-compile.stdout.log") `
        -RedirectStandardError (Join-Path $logRoot "zookeeper-seed-compile.stderr.log")
    if ($compile.ExitCode -ne 0) { throw "ZooKeeper partition seeder compilation failed" }
    $seedClassPath = "$seedClasses;$gatewayClassPath"
    $seed = Start-Process -FilePath "java.exe" -ArgumentList @("-cp", $seedClassPath, "ZkSeeder", "127.0.0.1:32182") `
        -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput (Join-Path $logRoot "zookeeper-seed.stdout.log") `
        -RedirectStandardError (Join-Path $logRoot "zookeeper-seed.stderr.log")
    if ($seed.ExitCode -ne 0) { throw "ZooKeeper partition seed failed" }

    $orderA = Start-JavaProcess "ordersvr-a" $orderARoot $orderClassPath "OrderSvr" @() $backendRoot $logRoot
    $processIds += $orderA.Id
    Wait-Port 33136 60 "OrderSvrA"
    Wait-Port 19101 60 "OrderSvrA replication"

    $orderB = Start-JavaProcess "ordersvr-b" $orderBRoot $orderClassPath "OrderSvr" @() $backendRoot $logRoot
    $processIds += $orderB.Id
    Wait-Port 33236 60 "OrderSvrB"
    Wait-Port 19102 60 "OrderSvrB replication"

    $gateway = Start-JavaProcess "gateway" $gatewayRoot $gatewayClassPath "GW" @() $backendRoot $logRoot
    $processIds += $gateway.Id
    Wait-Port 3032 60 "GW HTTP"
    $gatewayLog = Join-Path $logRoot "gateway.stdout.log"
    foreach ($probe in @(
        @{ Symbol="BTCUSDT"; Port=33136; Node="OrderSvrA" },
        @{ Symbol="ETHUSDT"; Port=33236; Node="OrderSvrB" }
    )) {
        $probePayload = @{
            serverName="OrderSvr"; method="__cluster_route_readiness__"
            key=("WEB_E2E" + [char]31 + "4" + [char]31 + $probe.Symbol); content=@{
                Location="WEB_E2E"; MarketIndicator="4"; SecurityID=$probe.Symbol
            }
        } | ConvertTo-Json -Depth 5 -Compress
        $probePath = Join-Path $logRoot ("probe-" + $probe.Symbol + ".json")
        $probeResponsePath = Join-Path $logRoot ("probe-response-" + $probe.Symbol + ".json")
        Write-Utf8 $probePath $probePayload
        [void](Invoke-GwRequest $probePath $probeResponsePath 5)
        Wait-LogPattern $gatewayLog ("GwClient connected to Host:127\.0\.0\.1,Port:" + $probe.Port) 60 ("GW -> " + $probe.Node + " connection")
    }

    $requests = @(
        @{ Symbol="BTCUSDT"; ClOrdId="LOCAL-AB-BTC-$runId" },
        @{ Symbol="ETHUSDT"; ClOrdId="LOCAL-AB-ETH-$runId" }
    )
    foreach ($request in $requests) {
        $payload = @{
            serverName="OrderSvr"; method="placeOrder"
            key=("WEB_E2E" + [char]31 + "4" + [char]31 + $request.Symbol); content=@{
                OCType="OPEN"; OrderQty="0.001"; OrdType="Limit"; ClOrdID=$request.ClOrdId
                Terminal="ClusterE2E"; CloseBy="liq"; AlgoName="cross"; Side="Buy"; Price="100"
                UserID="cluster-e2e"; MarketIndicator="4"; TimeInForce="GTC"
                SecurityID=$request.Symbol; Location="WEB_E2E"; ReduceOnly="true"
            }
        } | ConvertTo-Json -Depth 8 -Compress
        $responsePath = Join-Path $logRoot ("response-" + $request.Symbol + ".json")
        $requestPath = Join-Path $logRoot ("request-" + $request.Symbol + ".json")
        Write-Utf8 $requestPath $payload
        $requestExit = Invoke-GwRequest $requestPath $responsePath 15
        if ($requestExit -ne 0) { throw "GW request failed for $($request.Symbol), curl exit=$requestExit" }
    }

    Start-Sleep -Seconds 2
    $aLog = Get-Content -LiteralPath (Join-Path $logRoot "ordersvr-a.stdout.log") -Raw
    $bLog = Get-Content -LiteralPath (Join-Path $logRoot "ordersvr-b.stdout.log") -Raw
    if ($aLog -notmatch 'ORDER_CLUSTER_COMMAND_RECORDED node:OrderSvrA, partition:P027.*replicaStatus:OK') {
        throw "BTCUSDT was not routed to OrderSvrA and synchronously replicated"
    }
    if ($bLog -notmatch 'ORDER_CLUSTER_COMMAND_RECORDED node:OrderSvrB, partition:P132.*replicaStatus:OK') {
        throw "ETHUSDT was not routed to OrderSvrB and synchronously replicated"
    }

    $manifest = [ordered]@{
        result = "PASS"
        runId = $runId
        runRoot = $runRoot
        gatewayHttp = "http://127.0.0.1:3032"
        routes = @(
            [ordered]@{ key="WEB_E2E/4/BTCUSDT"; partition="P027"; primary="OrderSvrA"; replica="OrderSvrB" },
            [ordered]@{ key="WEB_E2E/4/ETHUSDT"; partition="P132"; primary="OrderSvrB"; replica="OrderSvrA" }
        )
        pids = @($processIds)
    }
    $manifestPath = Join-Path $runRoot "result.json"
    Write-Utf8 $manifestPath ($manifest | ConvertTo-Json -Depth 6)
    Write-Step "PASS: OrderA + OrderB + GW routing and synchronous replica ACK"
    Write-Step "Evidence: $manifestPath"
    $testSucceeded = $true
} catch {
    Write-Utf8 (Join-Path $logRoot "harness-error.log") ($_ | Out-String)
    throw
} finally {
    if (-not $KeepRunning) {
        $launched = @(Get-CimInstance Win32_Process | Where-Object {
            $_.Name -eq "java.exe" -and $_.CommandLine -like "*order-ab-local*$runId*"
        })
        Write-Utf8 (Join-Path $logRoot "cleanup.log") ("Launcher PIDs: " + ($processIds -join ",") +
            "; runtime PIDs: " + (($launched | ForEach-Object { $_.ProcessId }) -join ","))
        foreach ($runtimeProcess in $launched) {
            Stop-Process -Id $runtimeProcess.ProcessId -Force -ErrorAction SilentlyContinue
        }
        foreach ($processId in @($processIds | Sort-Object -Descending)) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }
    } elseif ($testSucceeded) {
        Write-Step "Processes kept running by request; PID list is in result.json"
    }
}
