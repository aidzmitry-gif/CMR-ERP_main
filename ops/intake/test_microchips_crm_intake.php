<?php

declare(strict_types=1);

require_once __DIR__ . '/microchips_crm_intake.php';

function testAssert(bool $condition, string $message): void
{
    if (!$condition) {
        throw new RuntimeException('ASSERTION FAILED: ' . $message);
    }
}

function testSame(mixed $expected, mixed $actual, string $message): void
{
    if ($expected !== $actual) {
        throw new RuntimeException(
            'ASSERTION FAILED: ' . $message . "\nExpected: "
            . var_export($expected, true) . "\nActual: " . var_export($actual, true)
        );
    }
}

function testReadJson(string $path): array
{
    $value = json_decode((string) file_get_contents($path), true, 512, JSON_THROW_ON_ERROR);
    testAssert(is_array($value), 'JSON object expected: ' . $path);
    return $value;
}

function testFiles(string $directory): array
{
    return glob($directory . DIRECTORY_SEPARATOR . '*.json') ?: [];
}

$spool = sys_get_temp_dir() . DIRECTORY_SEPARATOR . 'microchips-crm-intake-test-' . bin2hex(random_bytes(6));
$token = 'test-token-never-in-payload';
$transportCalls = [];
$transportResponses = [];

$transport = static function (string $method, string $url, array $headers, ?string $body) use (&$transportCalls, &$transportResponses): array {
    $transportCalls[] = ['method' => $method, 'url' => $url, 'headers' => $headers, 'body' => $body];
    $response = array_shift($transportResponses);
    if ($response instanceof Throwable) {
        throw $response;
    }
    return $response ?? ['http_code' => 500, 'body' => '{}'];
};

try {
    microchipsCrmIntakeEnsurePrivateDirectory($spool);
    testAssert(is_dir($spool . DIRECTORY_SEPARATOR . 'pending'), 'pending directory created on native filesystem');

    // Golden digests were generated from G04's actual IntakeRequestIn and
    // _prepare() path.  They cover contact cleanup, escaped Unicode, default
    // fields, file metadata, and Legat optional fields independently of the
    // producer's wire-byte digest.
    $goldenRequests = [
        [
            'request' => [
                'namespace' => 'enersys.by',
                'source_id' => 'mottor:1191119:123',
                'delivery_id' => 'mottor:1191119:123:initial',
                'lead' => [
                    'name' => 'Тест 😀',
                    'email' => '  USER@EXAMPLE.INVALID  ',
                    'phone' => ' ',
                    'message' => "Строка\nhttps://enersys.by/",
                ],
            ],
            'hash' => '6b393793cb5d3f0394b1d4cf64e9c09bc1b753d4609f7fa76953535d7b817616',
        ],
        [
            'request' => [
                'namespace' => 'admin@enersys.by',
                'identity_namespace' => 'microchips.by',
                'source_id' => 'form:3:result:999',
                'delivery_id' => 'mail:test',
                'lead' => ['message' => 'Копия'],
                'files' => [[
                    'file_id' => '2',
                    'filename' => 'Заявка.pdf',
                    'data_url' => 'data:application/pdf;base64,JVBERi0xLjQKaW50YWtlIHN5bnRoZXRpYwo=',
                    'size_bytes' => 26,
                    'sha256' => 'e23bd2d21f56b0049018f97578f48a29a939e002ae670eb9c4be8da9401dca5c',
                ]],
            ],
            'hash' => '2c399b9df7316b758311000efe231d962d5e656f442e1f6be6179093801c74ce',
        ],
        [
            'request' => [
                'namespace' => 'zakupki.legat.by',
                'source_id' => 'tender:123:lot:2',
                'delivery_id' => 'mail:abc:lot:2',
                'template_id' => 2344,
                'tender_id' => '123',
                'lot_id' => '2',
                'lead' => ['message' => 'Тендер'],
                'subject' => 'Закупка',
            ],
            'hash' => '38fee322b53ec4effab64c5cda4d4ccee3f5e0e5afde3e3840f4383fb45d1f40',
        ],
    ];
    foreach ($goldenRequests as $golden) {
        testSame($golden['hash'], microchipsCrmIntakeReceiverPayloadHash($golden['request']), 'G04 canonical receiver hash golden fixture');
    }

    $fsyncFailurePath = $spool . DIRECTORY_SEPARATOR . 'pending' . DIRECTORY_SEPARATOR . 'fsync-failure.json';
    $fsyncRejected = false;
    try {
        microchipsCrmIntakeAtomicCreate($fsyncFailurePath, '{}', static fn (mixed $handle): bool => false, static fn (string $directory): bool => true);
    } catch (RuntimeException $error) {
        $fsyncRejected = str_contains($error->getMessage(), 'fsync');
    }
    testAssert($fsyncRejected, 'file fsync failure is fail-closed');
    testAssert(!is_file($fsyncFailurePath), 'failed file fsync leaves no published file');
    $replaceFsyncFailurePath = $spool . DIRECTORY_SEPARATOR . 'status' . DIRECTORY_SEPARATOR . 'replace-fsync-failure.json';
    $replaceFsyncRejected = false;
    try {
        microchipsCrmIntakeAtomicReplace($replaceFsyncFailurePath, '{}', static fn (mixed $handle): bool => false, static fn (string $directory): bool => true);
    } catch (RuntimeException $error) {
        $replaceFsyncRejected = str_contains($error->getMessage(), 'fsync');
    }
    testAssert($replaceFsyncRejected, 'status replace fsync failure is fail-closed');
    testAssert(!is_file($replaceFsyncFailurePath), 'failed status fsync leaves no published file');
    $directoryFsyncFailurePath = $spool . DIRECTORY_SEPARATOR . 'pending' . DIRECTORY_SEPARATOR . 'directory-fsync-failure.json';
    $directoryFsyncRejected = false;
    try {
        microchipsCrmIntakeAtomicCreate($directoryFsyncFailurePath, '{}', static fn (mixed $handle): bool => true, static fn (string $directory): bool => false);
    } catch (RuntimeException $error) {
        $directoryFsyncRejected = str_contains($error->getMessage(), 'directory fsync');
    }
    testAssert($directoryFsyncRejected, 'directory fsync failure is fail-closed');
    testAssert(is_file($directoryFsyncFailurePath), 'published source remains visible after directory fsync failure');
    @unlink($directoryFsyncFailurePath);
    $moveSource = $spool . DIRECTORY_SEPARATOR . 'pending' . DIRECTORY_SEPARATOR . 'move-fsync-failure.json';
    microchipsCrmIntakeAtomicCreate($moveSource, '{}', static fn (mixed $handle): bool => true, static fn (string $directory): bool => true);
    $moveFsyncRejected = false;
    try {
        microchipsCrmIntakeMove($moveSource, $spool, 'done', static fn (string $directory): bool => false);
    } catch (RuntimeException $error) {
        $moveFsyncRejected = str_contains($error->getMessage(), 'directory fsync');
    }
    testAssert($moveFsyncRejected, 'move directory fsync failure is fail-closed');
    testAssert(is_file($moveSource), 'move fsync failure keeps pending retry name');
    $recoveredMove = microchipsCrmIntakeMove($moveSource, $spool, 'done', static fn (string $directory): bool => true);
    testAssert(is_file($recoveredMove), 'retry can recover a partially published move');
    @unlink($recoveredMove);
    @unlink($moveSource);

    $symlinkTarget = $spool . DIRECTORY_SEPARATOR . 'symlink-target';
    @mkdir($symlinkTarget, 0700);
    $symlinkSpool = $spool . DIRECTORY_SEPARATOR . 'symlink-spool';
    $symlinkCreated = @symlink($symlinkTarget, $symlinkSpool);
    if ($symlinkCreated) {
        $symlinkRejected = false;
        try {
            microchipsCrmIntakeEnsurePrivateDirectory($symlinkSpool . DIRECTORY_SEPARATOR . 'nested');
        } catch (RuntimeException $error) {
            $symlinkRejected = str_contains($error->getMessage(), 'symlink');
        }
        testAssert($symlinkRejected, 'symlink spool path is rejected');
        @unlink($symlinkSpool);
    }
    @rmdir($symlinkTarget);

    $configPath = $spool . DIRECTORY_SEPARATOR . 'config.php';
    file_put_contents($configPath, "<?php return ['token' => 'temporary', 'spool_dir' => " . var_export($spool, true) . "];\n");
    $configLink = $spool . DIRECTORY_SEPARATOR . 'config-link.php';
    $configLinkCreated = @symlink($configPath, $configLink);
    if ($configLinkCreated) {
        $configRejected = false;
        try {
            microchipsCrmIntakeLoadConfig($configLink);
        } catch (RuntimeException $error) {
            $configRejected = str_contains($error->getMessage(), 'symlink');
        }
        testAssert($configRejected, 'symlink config path is rejected');
        @unlink($configLink);
    }
    @unlink($configPath);

    $answers = [
        'CLIENT_NAME' => ['answer-1' => ['USER_TEXT' => 'Алексей', 'VALUE' => 'metadata-name']],
        'COMPANY' => ['answer-2' => ['ANSWER_TEXT' => 'ООО Тест', 'VALUE' => 'metadata-company']],
        'PHONE' => '+375290000000',
        'EMAIL' => 'a@example.invalid',
        'REGION' => 'Минск',
        'PRODUCT' => 'Battery',
        'MESSAGE' => 'Нужна консультация',
        'UTM_SOURCE' => 'test',
        'UTM_MEDIUM' => 'form',
        'UTM_CAMPAIGN' => 'crm-intake-test',
        'FORM_PAGE_URL' => ['answer-3' => ['USER_TEXT' => 'https://microchips.by/test', 'VALUE' => 'metadata-url']],
        'SOURCE_URL' => 'https://microchips.by/test?source=form',
    ];
    $queued = microchipsCrmIntakeQueueBitrixResult(1, 101, $answers, ['spool_dir' => $spool]);
    testSame('spooled', $queued['state'], 'target form is spooled before HTTP');
    $pending = testFiles($spool . DIRECTORY_SEPARATOR . 'pending');
    testSame(1, count($pending), 'one immutable pending form envelope');
    $envelope = testReadJson($pending[0]);
    testSame('form:1:result:101', $envelope['source_id'], 'form source identity');
    testSame('form:1:result:101', $envelope['delivery_id'], 'delivery identity equals source identity');
    testSame('https://microchips.by/test?source=form', $envelope['request']['source_url'], 'optional source_url is top-level');
    testSame('f0596790466f20ed7fa6862820730f137a376fa6b50c70e84e443047be9db600', $envelope['payload_sha256'], 'microchips request matches G04 canonical hash');
    testAssert($envelope['wire_sha256'] !== $envelope['payload_sha256'], 'wire and receiver canonical hashes are separate');
    testAssert(strpos((string) file_get_contents($pending[0]), $token) === false, 'token absent from queue');
    $originalBody = $envelope['request_json'];

    $excluded = microchipsCrmIntakeQueueBitrixResult(7, 102, $answers, ['spool_dir' => $spool]);
    testSame('ignored_excluded_form', $excluded['state'], 'non-target form excluded');
    testSame(1, count(testFiles($spool . DIRECTORY_SEPARATOR . 'pending')), 'excluded form not queued');

    $duplicate = microchipsCrmIntakeQueueBitrixResult(1, 101, $answers, ['spool_dir' => $spool]);
    testSame('duplicate', $duplicate['state'], 'same source is idempotently deduplicated locally');
    $conflictAnswers = $answers;
    $conflictAnswers['MESSAGE'] = 'different payload';
    $conflict = microchipsCrmIntakeQueueBitrixResult(1, 101, $conflictAnswers, ['spool_dir' => $spool]);
    testSame('conflict_review', $conflict['state'], 'same identity with changed payload goes to review');
    testSame($originalBody, testReadJson($pending[0])['request_json'], 'original envelope is immutable');
    testSame(1, count(testFiles($spool . DIRECTORY_SEPARATOR . 'review')), 'conflict retained in review');

    $payloadHash = $envelope['payload_sha256'];
    $transportResponses[] = [
        'http_code' => 202,
        'body' => json_encode([
            'receipt_id' => 'r-queued-101',
            'status' => 'queued',
            'source_id' => 'form:1:result:101',
            'delivery_id' => 'form:1:result:101',
            'namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
            'identity_namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
            'payload_sha256' => $payloadHash,
            'lead_id' => null,
            'files' => [],
        ], JSON_THROW_ON_ERROR),
    ];
    $consumed = microchipsCrmIntakeConsume($spool, $token, $transport, 10, true);
    testSame(0, $consumed['errors'], 'queued receiver response succeeds');
    testSame('queued', microchipsCrmIntakeReadStatus($spool, 'form:1:result:101')['state'], 'queued state is durable');
    testSame(1, count(testFiles($spool . DIRECTORY_SEPARATOR . 'done')), 'queued raw envelope retained in done');
    testSame(1, count($transportCalls), 'one HTTP POST for queued response');
    testAssert(strpos((string) $transportCalls[0]['body'], $token) === false, 'token absent from POST body');
    testAssert(in_array('X-Intake-Token: ' . $token, $transportCalls[0]['headers'], true), 'token only sent as header');

    $again = microchipsCrmIntakeConsume($spool, $token, $transport, 10, true);
    testSame(0, $again['processed'], 'queued item is not posted again');
    testSame(1, count($transportCalls), 'queued item does not duplicate HTTP');

    $retry = microchipsCrmIntakeQueueBitrixResult(2, 202, $answers, ['spool_dir' => $spool]);
    testSame('spooled', $retry['state'], 'second target form spooled');
    $retryEnvelope = testReadJson($spool . DIRECTORY_SEPARATOR . 'pending' . DIRECTORY_SEPARATOR . hash('sha256', 'form:2:result:202') . '.json');
    $retryHash = $retryEnvelope['payload_sha256'];
    $transportResponses[] = [
        'http_code' => 503,
        'body' => json_encode([
            'receipt_id' => 'r-unavailable-202',
            'status' => 'unavailable',
            'source_id' => 'form:2:result:202',
            'delivery_id' => 'form:2:result:202',
            'namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
            'identity_namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
            'payload_sha256' => $retryHash,
            'lead_id' => null,
            'files' => [],
        ], JSON_THROW_ON_ERROR),
    ];
    $failed = microchipsCrmIntakeConsume($spool, $token, $transport, 10, true);
    testSame(1, $failed['errors'], 'valid unavailable response is retained for retry and is visible to CLI');
    testSame('unavailable', microchipsCrmIntakeReadStatus($spool, 'form:2:result:202')['state'], 'unavailable state is durable');
    testAssert(is_file($spool . DIRECTORY_SEPARATOR . 'pending' . DIRECTORY_SEPARATOR . hash('sha256', 'form:2:result:202') . '.json'), 'unavailable envelope remains pending');
    $transportResponses[] = [
        'http_code' => 202,
        'body' => json_encode([
            'receipt_id' => 'r-queued-202',
            'status' => 'queued',
            'source_id' => 'form:2:result:202',
            'delivery_id' => 'form:2:result:202',
            'namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
            'identity_namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
            'payload_sha256' => $retryHash,
            'lead_id' => null,
            'files' => [],
        ], JSON_THROW_ON_ERROR),
    ];
    $retried = microchipsCrmIntakeConsume($spool, $token, $transport, 10, true);
    testSame(0, $retried['errors'], 'same immutable body retries successfully');
    testSame($transportCalls[count($transportCalls) - 2]['body'], $transportCalls[count($transportCalls) - 1]['body'], 'retry body is byte-for-byte unchanged');

    $delivered = microchipsCrmIntakeQueueBitrixResult(9, 909, $answers, ['spool_dir' => $spool]);
    testSame('spooled', $delivered['state'], 'delivered test form is spooled');
    $deliveredEnvelope = testReadJson($spool . DIRECTORY_SEPARATOR . 'pending' . DIRECTORY_SEPARATOR . hash('sha256', 'form:9:result:909') . '.json');
    $deliveredHash = $deliveredEnvelope['payload_sha256'];
    $transportResponses[] = [
        'http_code' => 200,
        'body' => json_encode([
            'receipt_id' => 'r-delivered-909',
            'status' => 'delivered',
            'namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
            'identity_namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
            'source_id' => 'form:9:result:909',
            'delivery_id' => 'form:9:result:909',
            'payload_sha256' => $deliveredHash,
            'lead_id' => 9009,
            'files' => [],
        ], JSON_THROW_ON_ERROR),
    ];
    $transportResponses[] = [
        'http_code' => 200,
        'body' => json_encode([
            'receipt_id' => 'r-delivered-909',
            'status' => 'delivered',
            'namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
            'identity_namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
            'source_id' => 'form:9:result:909',
            'delivery_id' => 'form:9:result:909',
            'payload_sha256' => $deliveredHash,
            'lead_id' => 9009,
            'files' => [],
        ], JSON_THROW_ON_ERROR),
    ];
    $callCountBeforeDelivered = count($transportCalls);
    $deliveredConsumed = microchipsCrmIntakeConsume($spool, $token, $transport, 10, true);
    testSame(0, $deliveredConsumed['errors'], 'POST delivered is confirmed by GET');
    testSame(2, count($transportCalls) - $callCountBeforeDelivered, 'delivered item performs POST and mandatory GET');
    testSame('delivered', microchipsCrmIntakeReadStatus($spool, 'form:9:result:909')['state'], 'GET-confirmed delivered state is durable');

    $expectedFile = [['file_id' => 'f1', 'filename' => 'quote.pdf', 'sha256' => str_repeat('a', 64)]];
    $fileReceipt = microchipsCrmIntakeValidateReceipt([
        'receipt_id' => 'r-file',
        'status' => 'delivered',
        'namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
        'identity_namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
        'source_id' => 'form:1:result:101',
        'delivery_id' => 'form:1:result:101',
        'payload_sha256' => $payloadHash,
        'lead_id' => 77,
        'files' => [[
            'file_id' => 'f1', 'filename' => 'quote.pdf', 'sha256' => str_repeat('a', 64), 'attachment_id' => 123,
        ]],
    ], 'form:1:result:101', $payloadHash, $expectedFile, 200);
    testSame('77', $fileReceipt['lead_id'], 'delivered receipt requires positive lead ID');
    testSame('123', (string) $fileReceipt['files'][0]['attachment_id'], 'delivered receipt retains attachment ID');
    $fileMismatchRejected = false;
    try {
        microchipsCrmIntakeValidateReceipt([
            'receipt_id' => 'r-file',
            'status' => 'delivered',
            'namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
            'identity_namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
            'source_id' => 'form:1:result:101',
            'delivery_id' => 'form:1:result:101',
            'payload_sha256' => $payloadHash,
            'lead_id' => 77,
            'files' => [[
                'file_id' => 'f1', 'filename' => 'quote.pdf', 'sha256' => str_repeat('b', 64), 'attachment_id' => null,
            ]],
        ], 'form:1:result:101', $payloadHash, $expectedFile, 200);
    } catch (RuntimeException $error) {
        $fileMismatchRejected = str_contains($error->getMessage(), 'attachment_id') || str_contains($error->getMessage(), 'SHA');
    }
    testAssert($fileMismatchRejected, 'delivered file SHA and attachment ID are checked');

    $getOnlyResponse = [
        'http_code' => 200,
        'body' => json_encode([
            'receipt_id' => 'r-queued-101',
            'status' => 'queued',
            'namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
            'identity_namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
            'source_id' => 'form:1:result:101',
            'delivery_id' => 'form:1:result:101',
            'payload_sha256' => $payloadHash,
            'lead_id' => null,
            'files' => [],
        ], JSON_THROW_ON_ERROR),
    ];
    $getTransport = static function (string $method, string $url, array $headers, ?string $body) use (&$getOnlyResponse, $token): array {
        testSame('GET', $method, 'receipt uses GET');
        testSame(MICROCHIPS_CRM_INTAKE_ENDPOINT . '/receipts/r-queued-101', $url, 'receipt URL');
        testSame(null, $body, 'receipt GET has no body');
        testAssert(in_array('X-Intake-Token: ' . $token, $headers, true), 'receipt token uses header');
        return $getOnlyResponse;
    };
    $receipt = microchipsCrmIntakeGetReceipt('r-queued-101', $token, $getTransport);
    testSame('r-queued-101', $receipt['receipt_id'], 'receipt response returned');

    $truncatedAnswers = $answers;
    $truncatedAnswers['PHONE'] = str_repeat('7', MICROCHIPS_CRM_INTAKE_MAX_PHONE_BYTES + 1);
    $truncated = microchipsCrmIntakeQueueBitrixResult(3, 303, $truncatedAnswers, ['spool_dir' => $spool]);
    testSame('spooled_review_required', $truncated['state'], 'field truncation is review-only');
    $transportCallCountBeforeReview = count($transportCalls);
    $truncatedReview = microchipsCrmIntakeConsume($spool, $token, $transport, 10, true);
    testSame($transportCallCountBeforeReview, count($transportCalls), 'truncated field is not posted');
    testSame('failed_review', microchipsCrmIntakeReadStatus($spool, 'form:3:result:303')['state'], 'truncated source is retained for review');

    $order = microchipsCrmIntakeOnSaleOrderSaved([
        'ENTITY' => [
            'ID' => 501,
            'customer' => ['name' => 'Заказчик', 'company' => 'Компания'],
            'contact' => ['phone' => '+375291111111', 'email' => 'order@example.invalid'],
            'properties' => ['CITY' => 'Минск'],
            'products' => [['ID' => 9, 'NAME' => 'Pack', 'QUANTITY' => 3, 'PRICE' => '10.00', 'TOTAL' => '30.00']],
            'totals' => ['total' => '30.00', 'currency' => 'BYN'],
            'delivery' => ['name' => 'Самовывоз'],
            'comment' => 'Позвонить утром',
        ],
        'IS_NEW' => true,
    ], ['spool_dir' => $spool]);
    testSame('spooled', $order['state'], 'new order is spooled');
    $orderEnvelope = testReadJson($spool . DIRECTORY_SEPARATOR . 'pending' . DIRECTORY_SEPARATOR . hash('sha256', 'order:501') . '.json');
    testSame('order:501', $orderEnvelope['source_id'], 'order source identity');
    testSame('order:501', $orderEnvelope['delivery_id'], 'order delivery identity');
    testAssert(str_contains($orderEnvelope['request']['lead']['message'], 'Позвонить утром'), 'order comment captured');
    testAssert(str_contains($orderEnvelope['request']['lead']['message'], 'QUANTITY') || str_contains($orderEnvelope['request']['lead']['message'], 'quantity'), 'order quantities captured');
    $existingOrder = microchipsCrmIntakeOnSaleOrderSaved(['ENTITY' => ['ID' => 502], 'IS_NEW' => false], ['spool_dir' => $spool]);
    testSame('ignored_existing_order', $existingOrder['state'], 'existing order is ignored');

    $orderWithFile = microchipsCrmIntakeOnSaleOrderSaved([
        'ENTITY' => ['ID' => 503, 'files' => [['id' => 'f1', 'name' => 'quote.pdf']]],
        'IS_NEW' => true,
    ], ['spool_dir' => $spool]);
    testSame('spooled_review_required', $orderWithFile['state'], 'order files are retained for review');
    $orderHash = $orderEnvelope['payload_sha256'];
    $transportResponses[] = [
        'http_code' => 202,
        'body' => json_encode([
            'receipt_id' => 'r-queued-order-501',
            'status' => 'queued',
            'namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
            'identity_namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
            'source_id' => 'order:501',
            'delivery_id' => 'order:501',
            'payload_sha256' => $orderHash,
            'lead_id' => null,
            'files' => [],
        ], JSON_THROW_ON_ERROR),
    ];
    $reviewBeforeConsume = count(testFiles($spool . DIRECTORY_SEPARATOR . 'review'));
    $reviewed = microchipsCrmIntakeConsume($spool, $token, $transport, 10, true);
    testAssert($reviewed['processed'] >= 1, 'review item is processed visibly');
    testAssert(count(testFiles($spool . DIRECTORY_SEPARATOR . 'review')) >= $reviewBeforeConsume + 1, 'order file envelope remains in review');

    $notConfirmed = microchipsCrmIntakeQueueBitrixResult(10, 910, $answers, ['spool_dir' => $spool]);
    testSame('spooled', $notConfirmed['state'], 'GET failure test form is spooled');
    $notConfirmedEnvelope = testReadJson($spool . DIRECTORY_SEPARATOR . 'pending' . DIRECTORY_SEPARATOR . hash('sha256', 'form:10:result:910') . '.json');
    $notConfirmedHash = $notConfirmedEnvelope['payload_sha256'];
    foreach ([
        ['http_code' => 200, 'status' => 'delivered', 'lead_id' => 9010],
        ['http_code' => 202, 'status' => 'queued', 'lead_id' => null],
    ] as $reply) {
        $transportResponses[] = [
            'http_code' => $reply['http_code'],
            'body' => json_encode([
                'receipt_id' => 'r-not-confirmed-910',
                'status' => $reply['status'],
                'namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
                'identity_namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
                'source_id' => 'form:10:result:910',
                'delivery_id' => 'form:10:result:910',
                'payload_sha256' => $notConfirmedHash,
                'lead_id' => $reply['lead_id'],
                'files' => [],
            ], JSON_THROW_ON_ERROR),
        ];
    }
    $notConfirmedConsumed = microchipsCrmIntakeConsume($spool, $token, $transport, 10, true);
    testSame(1, $notConfirmedConsumed['errors'], 'POST delivered without delivered GET remains retryable');
    testAssert(is_file($spool . DIRECTORY_SEPARATOR . 'pending' . DIRECTORY_SEPARATOR . hash('sha256', 'form:10:result:910') . '.json'), 'GET-unconfirmed envelope remains pending');
    testSame('transport_or_validation_error', microchipsCrmIntakeReadStatus($spool, 'form:10:result:910')['state'], 'GET-unconfirmed state is visible');

    echo "PASS: microchips CRM intake producer tests\n";
} finally {
    foreach (['pending', 'done', 'failed', 'review', 'status'] as $directory) {
        $files = testFiles($spool . DIRECTORY_SEPARATOR . $directory);
        foreach ($files as $file) {
            @unlink($file);
        }
    }
    @unlink($spool . DIRECTORY_SEPARATOR . '.enqueue.lock');
    @unlink($spool . DIRECTORY_SEPARATOR . '.consumer.lock');
    foreach (['pending', 'done', 'failed', 'review', 'status'] as $directory) {
        @rmdir($spool . DIRECTORY_SEPARATOR . $directory);
    }
    @rmdir($spool);
}
