<?php

declare(strict_types=1);

require_once __DIR__ . DIRECTORY_SEPARATOR . 'microchips_crm_intake.php';

if ($argc !== 2 || trim($argv[1]) === '') {
    fwrite(STDERR, "usage: test_microchips_crm_intake_asgi_bridge.php SPOOL_DIR\n");
    exit(2);
}

$spool = $argv[1];
$sourceId = 'form:1:result:987654';
$token = 'test-intake-only';
$answers = [
    'CLIENT_NAME' => 'Synthetic PHP Buyer',
    'COMPANY' => 'Synthetic Acceptance Co',
    'EMAIL' => 'php-intake@example.invalid',
    'PRODUCT' => 'Synthetic battery',
    'MESSAGE' => 'G05 PHP producer to local ASGI acceptance',
];

$transport = static function (string $method, string $url, array $headers, ?string $body): array {
    $event = [
        'kind' => 'transport',
        'method' => $method,
        'url' => $url,
        'headers' => $headers,
        'body' => $body,
    ];
    fwrite(STDOUT, json_encode($event, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n");
    fflush(STDOUT);

    $line = fgets(STDIN);
    if ($line === false) {
        throw new RuntimeException('transport pipe closed');
    }
    $response = json_decode($line, true, 512, JSON_THROW_ON_ERROR);
    if (!is_array($response) || !isset($response['http_code']) || !array_key_exists('body', $response)) {
        throw new RuntimeException('transport response must contain http_code and body');
    }
    return $response;
};

try {
    $queued = microchipsCrmIntakeQueueBitrixResult(1, 987654, $answers, ['spool_dir' => $spool]);
    $consumed = microchipsCrmIntakeConsume($spool, $token, $transport, 10, true);
    $status = microchipsCrmIntakeReadStatus($spool, $sourceId);
    $pending = glob($spool . DIRECTORY_SEPARATOR . 'pending' . DIRECTORY_SEPARATOR . '*.json') ?: [];
    $done = glob($spool . DIRECTORY_SEPARATOR . 'done' . DIRECTORY_SEPARATOR . '*.json') ?: [];

    $result = [
        'kind' => 'result',
        'queue_state' => $queued['state'] ?? null,
        'source_id' => $sourceId,
        'consume' => $consumed,
        'status' => $status,
        'pending_count' => count($pending),
        'done_count' => count($done),
    ];
    fwrite(STDOUT, json_encode($result, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n");
    fflush(STDOUT);
} catch (Throwable $error) {
    fwrite(STDERR, 'bridge failed: ' . get_class($error) . ': ' . $error->getMessage() . "\n");
    exit(1);
}
