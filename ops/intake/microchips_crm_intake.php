<?php

declare(strict_types=1);

/**
 * Minimal, dependency-free producer for the microchips.by intake receiver.
 *
 * This file deliberately does not register Bitrix handlers.  The production
 * cutover is an operator action after the receiver contract is accepted.  The
 * functions below make the handler boundary explicit and are safe to require
 * from Bitrix local/php_interface code.
 */

const MICROCHIPS_CRM_INTAKE_NAMESPACE = 'microchips.by';
const MICROCHIPS_CRM_INTAKE_ENDPOINT = 'https://belakb.by/integrations/intake/v1';
const MICROCHIPS_CRM_INTAKE_MAX_PRODUCT_BYTES = 128;
const MICROCHIPS_CRM_INTAKE_MAX_MESSAGE_BYTES = 262144;
const MICROCHIPS_CRM_INTAKE_MAX_URL_BYTES = 2048;
const MICROCHIPS_CRM_INTAKE_MAX_NAME_BYTES = 255;
const MICROCHIPS_CRM_INTAKE_MAX_COMPANY_BYTES = 255;
const MICROCHIPS_CRM_INTAKE_MAX_PHONE_BYTES = 64;
const MICROCHIPS_CRM_INTAKE_MAX_EMAIL_BYTES = 128;
const MICROCHIPS_CRM_INTAKE_MAX_REGION_BYTES = 64;
const MICROCHIPS_CRM_INTAKE_MAX_UTM_BYTES = 128;

/** @var list<int> */
const MICROCHIPS_CRM_INTAKE_TARGET_FORM_IDS = [1, 2, 3, 4, 5, 6, 9, 10];

/** @return array<string, mixed> */
function microchipsCrmIntakeJsonDecode(string $json): array
{
    $decoded = json_decode($json, true, 512, JSON_THROW_ON_ERROR);

    if (!is_array($decoded)) {
        throw new RuntimeException('JSON object expected');
    }

    return $decoded;
}

function microchipsCrmIntakeJsonEncode(mixed $value): string
{
    return json_encode(
        $value,
        JSON_UNESCAPED_UNICODE
        | JSON_UNESCAPED_SLASHES
        | JSON_PRESERVE_ZERO_FRACTION
        | JSON_THROW_ON_ERROR
    );
}

/**
 * Return the key order used by Python json.dumps(sort_keys=True).  Lists keep
 * their receiver-defined order; only JSON objects are sorted recursively.
 */
function microchipsCrmIntakeCanonicalSort(mixed $value): mixed
{
    if (!is_array($value)) {
        return $value;
    }

    $sorted = [];
    foreach ($value as $key => $child) {
        $sorted[$key] = microchipsCrmIntakeCanonicalSort($child);
    }
    if (!array_is_list($sorted)) {
        ksort($sorted, SORT_STRING);
    }

    return $sorted;
}

/**
 * G04 hashes its Pydantic-normalised request, rather than the immutable wire
 * JSON.  Keep this encoder separate from the wire encoder: Python's
 * ensure_ascii=True and compact separators are part of the receiver contract.
 */
function microchipsCrmIntakeCanonicalJsonEncode(mixed $value): string
{
    return json_encode(
        microchipsCrmIntakeCanonicalSort($value),
        JSON_UNESCAPED_SLASHES
        | JSON_PRESERVE_ZERO_FRACTION
        | JSON_THROW_ON_ERROR
    );
}

/**
 * Shape the exact payload returned by G04's IntakeRequestIn.model_dump() and
 * _prepare().  Empty contact values become null and file data becomes the
 * validated metadata manifest.  Current microchips producers hold any file
 * source for review, so the file branch is defensive and never authorises a
 * file for delivery by itself.
 *
 * @param array<string, mixed> $request
 * @return array<string, mixed>
 */
function microchipsCrmIntakeReceiverCanonicalPayload(array $request): array
{
    $rawLead = is_array($request['lead'] ?? null) ? $request['lead'] : [];
    $contact = static function (mixed $value, bool $lower = false): ?string {
        if (!is_scalar($value) || $value === '') {
            return null;
        }
        $text = trim((string) $value);
        if ($lower) {
            $text = strtolower($text);
        }
        return $text === '' ? null : $text;
    };
    $text = static function (mixed $value): string {
        return is_scalar($value) ? (string) $value : '';
    };
    $lead = [
        'name' => $text($rawLead['name'] ?? ''),
        'company' => $text($rawLead['company'] ?? ''),
        'phone' => $contact($rawLead['phone'] ?? null),
        'email' => $contact($rawLead['email'] ?? null, true),
        'region' => $text($rawLead['region'] ?? ''),
        'product' => $text($rawLead['product'] ?? ''),
        'message' => $text($rawLead['message'] ?? ''),
        'utm_source' => $text($rawLead['utm_source'] ?? ''),
        'utm_medium' => $text($rawLead['utm_medium'] ?? ''),
        'utm_campaign' => $text($rawLead['utm_campaign'] ?? ''),
        'landing_url' => $text($rawLead['landing_url'] ?? ''),
    ];

    $files = [];
    foreach (is_array($request['files'] ?? null) ? $request['files'] : [] as $file) {
        if (!is_array($file)) {
            continue;
        }
        $dataUrl = is_scalar($file['data_url'] ?? null) ? (string) $file['data_url'] : '';
        $fileId = is_scalar($file['file_id'] ?? ($file['id'] ?? null))
            ? (string) ($file['file_id'] ?? $file['id']) : '';
        $filename = is_scalar($file['filename'] ?? ($file['name'] ?? null))
            ? (string) ($file['filename'] ?? $file['name']) : '';
        $metadata = [
            'file_id' => $fileId,
            'filename' => $filename,
            'content_type' => is_scalar($file['content_type'] ?? ($file['mime'] ?? null))
                ? (string) ($file['content_type'] ?? $file['mime']) : '',
            'size_bytes' => (int) ($file['size_bytes'] ?? ($file['size'] ?? 0)),
            'sha256' => is_scalar($file['sha256'] ?? null) ? (string) $file['sha256'] : '',
        ];
        if ($dataUrl !== '' && preg_match('/\Adata:([^;,]+);base64,(.*)\z/s', $dataUrl, $matches)) {
            $decoded = base64_decode($matches[2], true);
            if ($decoded !== false) {
                $metadata['content_type'] = $matches[1];
                $metadata['size_bytes'] = strlen($decoded);
                $metadata['sha256'] = hash('sha256', $decoded);
            }
        }
        $files[] = $metadata;
    }
    usort($files, static fn (array $left, array $right): int => strcmp($left['file_id'], $right['file_id']));

    return [
        'namespace' => $text($request['namespace'] ?? MICROCHIPS_CRM_INTAKE_NAMESPACE),
        'identity_namespace' => $text($request['identity_namespace'] ?? ($request['namespace'] ?? MICROCHIPS_CRM_INTAKE_NAMESPACE)),
        'source_id' => $text($request['source_id'] ?? ''),
        'delivery_id' => $text($request['delivery_id'] ?? ''),
        'lead' => $lead,
        'subject' => $text($request['subject'] ?? ''),
        'message_id' => $text($request['message_id'] ?? ''),
        'source_url' => $text($request['source_url'] ?? ''),
        'template_id' => array_key_exists('template_id', $request) ? $request['template_id'] : null,
        'tender_id' => array_key_exists('tender_id', $request) ? $request['tender_id'] : null,
        'lot_id' => array_key_exists('lot_id', $request) ? $request['lot_id'] : null,
        'files' => $files,
    ];
}

/** @param array<string, mixed> $request */
function microchipsCrmIntakeReceiverPayloadHash(array $request): string
{
    return hash('sha256', microchipsCrmIntakeCanonicalJsonEncode(
        microchipsCrmIntakeReceiverCanonicalPayload($request)
    ));
}

function microchipsCrmIntakeNow(): string
{
    return gmdate('c');
}

function microchipsCrmIntakeText(mixed $value): string
{
    if ($value === null) {
        return '';
    }

    if (is_bool($value)) {
        return $value ? '1' : '0';
    }

    if (is_scalar($value)) {
        return trim((string) $value);
    }

    if (is_array($value)) {
        $parts = [];
        foreach ($value as $item) {
            $part = microchipsCrmIntakeText($item);
            if ($part !== '') {
                $parts[] = $part;
            }
        }

        return trim(implode(', ', $parts));
    }

    return '';
}

/**
 * Limit by bytes while preserving a valid UTF-8 prefix where mbstring exists.
 * The unbounded source remains in the private raw_source spool field.
 */
function microchipsCrmIntakeLimitText(string $value, int $maxBytes, ?bool &$truncated = null): string
{
    $truncated = false;
    if (strlen($value) <= $maxBytes) {
        return $value;
    }

    $truncated = true;
    if (function_exists('mb_strcut')) {
        return mb_strcut($value, 0, $maxBytes, 'UTF-8');
    }

    $limited = substr($value, 0, $maxBytes);
    if (function_exists('mb_check_encoding')) {
        while ($limited !== '' && !mb_check_encoding($limited, 'UTF-8')) {
            $limited = substr($limited, 0, -1);
        }
    }

    return $limited;
}

function microchipsCrmIntakeNormaliseKey(string|int $key): string
{
    return strtoupper((string) preg_replace('/[^A-Za-z0-9]+/', '_', (string) $key));
}

/** @return mixed */
function microchipsCrmIntakeAnswerValue(mixed $value): mixed
{
    if (!is_array($value)) {
        return $value;
    }

    foreach (['USER_TEXT', 'ANSWER_TEXT', 'VALUE', 'VALUE_TEXT', 'TEXT', 'title', 'name'] as $key) {
        if (array_key_exists($key, $value)) {
            return microchipsCrmIntakeAnswerValue($value[$key]);
        }
    }

    // CFormResult answers are commonly SID => answer_id => answer row.  Walk
    // the first answer row but never stringify its metadata as user text.
    foreach ($value as $child) {
        if (!is_array($child)) {
            continue;
        }
        $candidate = microchipsCrmIntakeAnswerValue($child);
        if ($candidate !== null && microchipsCrmIntakeText($candidate) !== '') {
            return $candidate;
        }
    }

    return null;
}

/** @param array<int|string, mixed> $answers */
function microchipsCrmIntakeAnswer(array $answers, array $names): mixed
{
    $wanted = [];
    foreach ($names as $name) {
        $wanted[microchipsCrmIntakeNormaliseKey((string) $name)] = true;
    }

    foreach ($answers as $key => $value) {
        if (isset($wanted[microchipsCrmIntakeNormaliseKey($key)])) {
            return microchipsCrmIntakeAnswerValue($value);
        }
    }

    return null;
}

/** @param array<int|string, mixed> $answers */
function microchipsCrmIntakeAnswersMessage(array $answers, array $knownKeys): string
{
    $known = [];
    foreach ($knownKeys as $key) {
        $known[microchipsCrmIntakeNormaliseKey((string) $key)] = true;
    }

    $lines = [];
    foreach ($answers as $key => $value) {
        if (isset($known[microchipsCrmIntakeNormaliseKey($key)])) {
            continue;
        }

        $text = microchipsCrmIntakeText(microchipsCrmIntakeAnswerValue($value));
        if ($text !== '') {
            $lines[] = (string) $key . ': ' . $text;
        }
    }

    return implode("\n", $lines);
}

/**
 * Strip credentials and non-serialisable objects from the retained source.
 * Queue and status files never contain the receiver token.
 */
function microchipsCrmIntakeSanitiseRaw(mixed $value, ?string $key = null): mixed
{
    if ($key !== null && preg_match('/token|authorization|password|secret|cookie/i', $key)) {
        return '[redacted]';
    }

    if (is_array($value)) {
        $result = [];
        foreach ($value as $childKey => $childValue) {
            $result[(string) $childKey] = microchipsCrmIntakeSanitiseRaw($childValue, (string) $childKey);
        }

        return $result;
    }

    if (is_object($value)) {
        return ['object_class' => get_class($value)];
    }

    if (is_resource($value)) {
        return ['resource_type' => get_resource_type($value)];
    }

    return $value;
}

/** @param array<int|string, mixed> $files */
function microchipsCrmIntakeNormaliseFiles(array $files): array
{
    $normalised = [];
    foreach ($files as $key => $file) {
        if (is_scalar($file)) {
            $name = microchipsCrmIntakeLimitText((string) $file, 255);
            if ($name !== '') {
                $normalised[] = ['name' => $name];
            }
            continue;
        }

        if (!is_array($file)) {
            continue;
        }

        $item = [];
        foreach (['id', 'file_id', 'name', 'filename', 'size', 'mime', 'content_type', 'status'] as $field) {
            if (array_key_exists($field, $file) && is_scalar($file[$field])) {
                $item[$field] = microchipsCrmIntakeLimitText((string) $file[$field], 255);
            }
        }
        if ($item === []) {
            $item['key'] = (string) $key;
        }
        $normalised[] = $item;
    }

    return $normalised;
}

function microchipsCrmIntakeIsAbsolutePath(string $path): bool
{
    if ($path === '') {
        return false;
    }
    if ($path[0] === '/' || $path[0] === '\\') {
        return true;
    }
    return strlen($path) >= 3
        && ctype_alpha($path[0])
        && $path[1] === ':'
        && ($path[2] === '/' || $path[2] === '\\');
}

function microchipsCrmIntakePathInside(string $path, string $parent): bool
{
    $normalise = static function (string $item): string {
        return rtrim(strtolower(str_replace('\\', '/', $item)), '/') . '/';
    };

    return str_starts_with($normalise($path), $normalise($parent));
}

/**
 * Reject symlinks in the complete path, including an existing parent of a
 * not-yet-created leaf.  Queue paths must never be redirected outside the
 * configured private spool by a replaceable link.
 */
function microchipsCrmIntakeAssertNoSymlink(string $path): void
{
    $probe = $path;
    while (true) {
        if (is_link($probe)) {
            throw new RuntimeException('symlink path is not allowed: ' . $path);
        }
        $parent = dirname($probe);
        if ($parent === $probe) {
            break;
        }
        $probe = $parent;
    }
}

function microchipsCrmIntakeSyncHandle(mixed $handle, ?callable $syncHandle = null): void
{
    $synced = $syncHandle !== null
        ? $syncHandle($handle)
        : (function_exists('fsync') ? @fsync($handle) : false);
    if ($synced !== true) {
        throw new RuntimeException('fsync failed; durable write not confirmed');
    }
}

function microchipsCrmIntakeSyncDirectory(string $directory, ?callable $syncDirectory = null): void
{
    microchipsCrmIntakeAssertNoSymlink($directory);
    if ($syncDirectory !== null) {
        if ($syncDirectory($directory) !== true) {
            throw new RuntimeException('directory fsync failed; durable namespace update not confirmed');
        }
        return;
    }

    // The production host is Linux.  Windows PHP cannot portably open a
    // directory for fsync; file fsync remains active there for local tests.
    if (DIRECTORY_SEPARATOR === '\\') {
        return;
    }
    if (!function_exists('fsync')) {
        throw new RuntimeException('directory fsync is unavailable');
    }
    $handle = @fopen($directory, 'r');
    if ($handle === false) {
        throw new RuntimeException('cannot open directory for fsync');
    }
    try {
        microchipsCrmIntakeSyncHandle($handle);
    } finally {
        fclose($handle);
    }
}

function microchipsCrmIntakeEnsurePrivateDirectory(string $directory): string
{
    $directory = rtrim($directory, "\\/");
    $isFilesystemRoot = $directory === ''
        || $directory === '/'
        || $directory === '\\'
        || (strlen($directory) === 2 && ctype_alpha($directory[0]) && $directory[1] === ':');
    if ($isFilesystemRoot || !microchipsCrmIntakeIsAbsolutePath($directory)) {
        throw new InvalidArgumentException('spool_dir must be an absolute path');
    }
    microchipsCrmIntakeAssertNoSymlink($directory);

    $documentRoot = isset($_SERVER['DOCUMENT_ROOT']) ? (string) $_SERVER['DOCUMENT_ROOT'] : '';
    if ($documentRoot !== '' && microchipsCrmIntakePathInside($directory, $documentRoot)) {
        throw new RuntimeException('spool_dir must be outside the web root');
    }

    if (!is_dir($directory) && !@mkdir($directory, 0700, true) && !is_dir($directory)) {
        throw new RuntimeException('Cannot create spool directory');
    }
    @chmod($directory, 0700);
    if (DIRECTORY_SEPARATOR === '/' && ((fileperms($directory) & 0077) !== 0)) {
        throw new RuntimeException('spool directory is accessible by group or other users');
    }
    microchipsCrmIntakeSyncDirectory($directory);

    foreach (['pending', 'done', 'failed', 'review', 'status'] as $child) {
        $path = $directory . DIRECTORY_SEPARATOR . $child;
        microchipsCrmIntakeAssertNoSymlink($path);
        if (!is_dir($path) && !@mkdir($path, 0700) && !is_dir($path)) {
            throw new RuntimeException('Cannot create spool subdirectory: ' . $child);
        }
        @chmod($path, 0700);
        if (DIRECTORY_SEPARATOR === '/' && ((fileperms($path) & 0077) !== 0)) {
            throw new RuntimeException('spool subdirectory is accessible by group or other users: ' . $child);
        }
        microchipsCrmIntakeSyncDirectory($path);
    }
    // Persist the parent directory entries created above as well as each
    // child directory's own metadata.
    microchipsCrmIntakeSyncDirectory($directory);

    return $directory;
}

/** @return array{token: string, spool_dir: string, config_path: string} */
function microchipsCrmIntakeLoadConfig(?string $configPath = null): array
{
    $configuredPath = $configPath;
    if ($configuredPath === null || $configuredPath === '') {
        $fromEnvironment = getenv('MICROCHIPS_CRM_INTAKE_CONFIG');
        $configuredPath = is_string($fromEnvironment) && $fromEnvironment !== ''
            ? $fromEnvironment
            : '/etc/microchips-crm-intake/config.php';
    }

    if (!microchipsCrmIntakeIsAbsolutePath($configuredPath)) {
        throw new RuntimeException('config file is missing or not an absolute path');
    }
    microchipsCrmIntakeAssertNoSymlink($configuredPath);
    if (!is_file($configuredPath)) {
        throw new RuntimeException('config file is missing or not an absolute path');
    }
    $documentRoot = isset($_SERVER['DOCUMENT_ROOT']) ? (string) $_SERVER['DOCUMENT_ROOT'] : '';
    if ($documentRoot !== '' && microchipsCrmIntakePathInside($configuredPath, $documentRoot)) {
        throw new RuntimeException('config file must be outside the web root');
    }
    @chmod($configuredPath, 0600);
    if (DIRECTORY_SEPARATOR === '/' && ((fileperms($configuredPath) & 0077) !== 0)) {
        throw new RuntimeException('config file is accessible by group or other users');
    }

    $config = require $configuredPath;
    if (!is_array($config)) {
        throw new RuntimeException('config file must return an array');
    }
    $token = isset($config['token']) ? trim((string) $config['token']) : '';
    $spoolDir = isset($config['spool_dir']) ? trim((string) $config['spool_dir']) : '';
    if ($token === '' || $spoolDir === '') {
        throw new RuntimeException('config requires token and spool_dir');
    }

    return [
        'token' => $token,
        'spool_dir' => microchipsCrmIntakeEnsurePrivateDirectory($spoolDir),
        'config_path' => $configuredPath,
    ];
}

function microchipsCrmIntakeAtomicCreate(
    string $path,
    string $contents,
    ?callable $syncHandle = null,
    ?callable $syncDirectory = null
): bool
{
    $directory = dirname($path);
    microchipsCrmIntakeAssertNoSymlink($path);
    $temporary = $directory . DIRECTORY_SEPARATOR . '.' . basename($path) . '.tmp.' . bin2hex(random_bytes(8));
    $handle = @fopen($temporary, 'x+b');
    if ($handle === false) {
        throw new RuntimeException('Cannot create temporary spool file');
    }

    try {
        @chmod($temporary, 0600);
        if (fwrite($handle, $contents) !== strlen($contents) || !fflush($handle)) {
            throw new RuntimeException('Cannot write temporary spool file');
        }
        microchipsCrmIntakeSyncHandle($handle, $syncHandle);
    } catch (Throwable $error) {
        @unlink($temporary);
        throw $error;
    } finally {
        fclose($handle);
    }

    if (function_exists('link') && @link($temporary, $path)) {
        @unlink($temporary);
        microchipsCrmIntakeSyncDirectory($directory, $syncDirectory);
        return true;
    }
    if (file_exists($path)) {
        @unlink($temporary);
        return false;
    }
    if (@rename($temporary, $path)) {
        @chmod($path, 0600);
        microchipsCrmIntakeSyncDirectory($directory, $syncDirectory);
        return true;
    }

    @unlink($temporary);
    throw new RuntimeException('Cannot publish spool file');
}

function microchipsCrmIntakeAtomicReplace(
    string $path,
    string $contents,
    ?callable $syncHandle = null,
    ?callable $syncDirectory = null
): void
{
    $directory = dirname($path);
    microchipsCrmIntakeAssertNoSymlink($path);
    $temporary = $directory . DIRECTORY_SEPARATOR . '.' . basename($path) . '.tmp.' . bin2hex(random_bytes(8));
    $handle = @fopen($temporary, 'x+b');
    if ($handle === false) {
        @unlink($temporary);
        throw new RuntimeException('Cannot create temporary status file');
    }
    try {
        @chmod($temporary, 0600);
        if (fwrite($handle, $contents) !== strlen($contents) || !fflush($handle)) {
            throw new RuntimeException('Cannot write temporary status file');
        }
        microchipsCrmIntakeSyncHandle($handle, $syncHandle);
    } catch (Throwable $error) {
        @unlink($temporary);
        throw $error;
    } finally {
        fclose($handle);
    }

    if (!@rename($temporary, $path)) {
        // Windows does not replace an existing file with rename().  Status is
        // mutable; the fallback keeps the operation usable for local tests.
        if (DIRECTORY_SEPARATOR === '\\' && file_exists($path)) {
            @unlink($path);
            if (@rename($temporary, $path)) {
                @chmod($path, 0600);
                microchipsCrmIntakeSyncDirectory($directory, $syncDirectory);
                return;
            }
        }
        @unlink($temporary);
        throw new RuntimeException('Cannot publish status file');
    }
    @chmod($path, 0600);
    microchipsCrmIntakeSyncDirectory($directory, $syncDirectory);
}

/** @template T */
function microchipsCrmIntakeWithEnqueueLock(string $spoolDir, callable $callback): mixed
{
    $path = $spoolDir . DIRECTORY_SEPARATOR . '.enqueue.lock';
    microchipsCrmIntakeAssertNoSymlink($path);
    $handle = @fopen($path, 'c+b');
    if ($handle === false) {
        throw new RuntimeException('Cannot open enqueue lock');
    }
    @chmod($path, 0600);
    if (!flock($handle, LOCK_EX)) {
        fclose($handle);
        throw new RuntimeException('Cannot lock enqueue spool');
    }

    try {
        return $callback();
    } finally {
        flock($handle, LOCK_UN);
        fclose($handle);
    }
}

function microchipsCrmIntakeSourceHash(string $sourceId): string
{
    return hash('sha256', $sourceId);
}

function microchipsCrmIntakeStatusPath(string $spoolDir, string $statusKey): string
{
    return $spoolDir . DIRECTORY_SEPARATOR . 'status' . DIRECTORY_SEPARATOR . hash('sha256', $statusKey) . '.json';
}

/** @return array<string, mixed>|null */
function microchipsCrmIntakeReadStatus(string $spoolDir, string $statusKey): ?array
{
    $path = microchipsCrmIntakeStatusPath($spoolDir, $statusKey);
    microchipsCrmIntakeAssertNoSymlink($path);
    if (!is_file($path)) {
        return null;
    }

    $decoded = microchipsCrmIntakeJsonDecode((string) file_get_contents($path));
    return $decoded;
}

/** @param array<string, mixed> $status */
function microchipsCrmIntakeWriteStatus(string $spoolDir, string $statusKey, array $status): void
{
    microchipsCrmIntakeAtomicReplace(
        microchipsCrmIntakeStatusPath($spoolDir, $statusKey),
        microchipsCrmIntakeJsonEncode($status) . "\n"
    );
}

/** @param array<string, mixed> $patch */
function microchipsCrmIntakeUpdateStatus(string $spoolDir, string $statusKey, array $patch): array
{
    $status = microchipsCrmIntakeReadStatus($spoolDir, $statusKey) ?? [
        'schema' => 1,
        'status_key' => $statusKey,
        'attempts' => 0,
        'created_at' => microchipsCrmIntakeNow(),
    ];
    foreach ($patch as $key => $value) {
        $status[$key] = $value;
    }
    $status['updated_at'] = microchipsCrmIntakeNow();
    microchipsCrmIntakeWriteStatus($spoolDir, $statusKey, $status);
    return $status;
}

function microchipsCrmIntakeValidateSourceId(string $sourceId): void
{
    if (!preg_match('/\A(?:form:\d+:result:\d+|order:\d+)\z/', $sourceId)) {
        throw new InvalidArgumentException('source_id must be form:ID:result:ID or order:ID');
    }
}

/** @param array<string, mixed> $payload */
function microchipsCrmIntakeQueue(
    string $sourceId,
    array $payload,
    array $rawSource,
    string $spoolDir,
    array $metadata = []
): array {
    microchipsCrmIntakeValidateSourceId($sourceId);
    $spoolDir = microchipsCrmIntakeEnsurePrivateDirectory($spoolDir);

    $request = [
        'namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
        'source_id' => $sourceId,
        'delivery_id' => $sourceId,
    ];
    foreach ($payload as $key => $value) {
        $request[(string) $key] = $value;
    }
    if (!isset($request['lead']) || !is_array($request['lead'])) {
        throw new InvalidArgumentException('payload requires lead object');
    }
    $body = microchipsCrmIntakeJsonEncode($request);
    // Keep the immutable wire-byte digest separate from G04's canonical
    // Pydantic payload digest used in the receiver receipt.
    $wireHash = hash('sha256', $body);
    $payloadHash = microchipsCrmIntakeReceiverPayloadHash($request);
    $sourceHash = microchipsCrmIntakeSourceHash($sourceId);
    $pendingPath = $spoolDir . DIRECTORY_SEPARATOR . 'pending' . DIRECTORY_SEPARATOR . $sourceHash . '.json';
    $envelope = [
        'schema' => 1,
        'namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
        'source_id' => $sourceId,
        'delivery_id' => $sourceId,
        'wire_sha256' => $wireHash,
        'payload_sha256' => $payloadHash,
        'request' => $request,
        // Retries use this exact immutable body.  It is never rebuilt from
        // mutable source objects after the first spool write.
        'request_json' => $body,
        'raw_source' => microchipsCrmIntakeSanitiseRaw($rawSource),
        'metadata' => microchipsCrmIntakeSanitiseRaw($metadata),
        'created_at' => microchipsCrmIntakeNow(),
    ];
    $contents = microchipsCrmIntakeJsonEncode($envelope) . "\n";

    return microchipsCrmIntakeWithEnqueueLock($spoolDir, static function () use (
        $spoolDir,
        $sourceId,
        $sourceHash,
        $wireHash,
        $payloadHash,
        $pendingPath,
        $contents,
        $envelope,
        $metadata
    ): array {
        $existing = null;
        foreach (['pending', 'done', 'failed', 'review'] as $stateDirectory) {
            $candidate = $spoolDir . DIRECTORY_SEPARATOR . $stateDirectory . DIRECTORY_SEPARATOR . $sourceHash . '.json';
            microchipsCrmIntakeAssertNoSymlink($candidate);
            if (is_file($candidate)) {
                $existing = ['path' => $candidate, 'envelope' => microchipsCrmIntakeJsonDecode((string) file_get_contents($candidate))];
                break;
            }
        }

        if ($existing !== null) {
            $existingHash = (string) ($existing['envelope']['payload_sha256'] ?? '');
            if (hash_equals($existingHash, $payloadHash)) {
                $status = microchipsCrmIntakeReadStatus($spoolDir, $sourceId);
                if ($status === null && basename(dirname($existing['path'])) === 'pending') {
                    // Recover a crash between durable pending publication and
                    // the status write, but only after re-syncing the pending
                    // directory.  Never treat an unconfirmed file as sent.
                    microchipsCrmIntakeSyncDirectory(dirname($existing['path']));
                    $status = [
                        'schema' => 1,
                        'status_key' => $sourceId,
                        'source_id' => $sourceId,
                        'delivery_id' => $sourceId,
                        'namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
                        'wire_sha256' => $wireHash,
                        'payload_sha256' => $payloadHash,
                        'state' => isset($metadata['requires_review']) && $metadata['requires_review'] ? 'spooled_review_required' : 'spooled',
                        'attempts' => 0,
                        'created_at' => microchipsCrmIntakeNow(),
                        'updated_at' => microchipsCrmIntakeNow(),
                    ];
                    microchipsCrmIntakeWriteStatus($spoolDir, $sourceId, $status);
                }
                return [
                    'state' => 'duplicate',
                    'source_id' => $sourceId,
                    'payload_sha256' => $payloadHash,
                    'path' => $existing['path'],
                    'status' => $status['state'] ?? 'spooled',
                ];
            }

            $conflictKey = 'identity-conflict-' . $sourceHash . '-' . bin2hex(random_bytes(6));
            $conflictEnvelope = $envelope;
            $conflictEnvelope['metadata']['requires_review'] = true;
            $conflictEnvelope['metadata']['review_reason'] = 'identity_payload_conflict';
            $conflictPath = $spoolDir . DIRECTORY_SEPARATOR . 'review' . DIRECTORY_SEPARATOR . $conflictKey . '.json';
            microchipsCrmIntakeAtomicCreate($conflictPath, microchipsCrmIntakeJsonEncode($conflictEnvelope) . "\n");
            microchipsCrmIntakeWriteStatus($spoolDir, $conflictKey, [
                'schema' => 1,
                'status_key' => $conflictKey,
                'source_id' => $sourceId,
                'delivery_id' => $sourceId,
                'wire_sha256' => $wireHash,
                'payload_sha256' => $payloadHash,
                'state' => 'failed_review',
                'review_reason' => 'identity_payload_conflict',
                'attempts' => 0,
                'created_at' => microchipsCrmIntakeNow(),
                'updated_at' => microchipsCrmIntakeNow(),
            ]);

            return [
                'state' => 'conflict_review',
                'source_id' => $sourceId,
                'payload_sha256' => $payloadHash,
                'path' => $conflictPath,
            ];
        }

        if (!microchipsCrmIntakeAtomicCreate($pendingPath, $contents)) {
            throw new RuntimeException('pending spool race; inspect status before retrying');
        }

        microchipsCrmIntakeWriteStatus($spoolDir, $sourceId, [
            'schema' => 1,
            'status_key' => $sourceId,
            'source_id' => $sourceId,
            'delivery_id' => $sourceId,
            'namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
            'wire_sha256' => $wireHash,
            'payload_sha256' => $payloadHash,
            'state' => isset($metadata['requires_review']) && $metadata['requires_review'] ? 'spooled_review_required' : 'spooled',
            'attempts' => 0,
            'created_at' => microchipsCrmIntakeNow(),
            'updated_at' => microchipsCrmIntakeNow(),
        ]);

        return [
            'state' => isset($metadata['requires_review']) && $metadata['requires_review'] ? 'spooled_review_required' : 'spooled',
            'source_id' => $sourceId,
            'payload_sha256' => $payloadHash,
            'path' => $pendingPath,
        ];
    });
}

/** @param array<int|string, mixed> $answers */
function microchipsCrmIntakeBuildFormPayload(array $answers, array $context = []): array
{
    $aliases = [
        'name' => ['NAME', 'FIO', 'FULL_NAME', 'PERSON', 'CLIENT_NAME', 'CONTACT_NAME'],
        'company' => ['COMPANY', 'ORGANIZATION', 'ORG', 'COMPANY_NAME'],
        'phone' => ['PHONE', 'TEL', 'TELEPHONE', 'PHONE_NUMBER'],
        'email' => ['EMAIL', 'E_MAIL', 'MAIL'],
        'region' => ['REGION', 'CITY', 'LOCATION'],
        'product' => ['PRODUCT', 'PRODUCT_NAME', 'SKU', 'MODEL', 'ITEM'],
        'message' => ['MESSAGE', 'COMMENT', 'QUESTION', 'TEXT', 'USER_MESSAGE'],
        'utm_source' => ['UTM_SOURCE'],
        'utm_medium' => ['UTM_MEDIUM'],
        'utm_campaign' => ['UTM_CAMPAIGN'],
        'landing_url' => ['LANDING_URL', 'PAGE_URL', 'URL', 'FORM_PAGE_URL', 'FIRST_LANDING_URL'],
        'source_url' => ['SOURCE_URL', 'ORIGINAL_URL'],
    ];
    foreach ($context['field_map'] ?? [] as $field => $fieldAliases) {
        if (isset($aliases[$field]) && is_array($fieldAliases)) {
            $aliases[$field] = array_values(array_unique(array_merge($aliases[$field], $fieldAliases)));
        }
    }

    $truncatedFields = [];
    $read = static function (string $field) use ($answers, $aliases, $context): mixed {
        if (array_key_exists($field, $context)) {
            return $context[$field];
        }
        return microchipsCrmIntakeAnswer($answers, $aliases[$field] ?? [$field]);
    };
    $bounded = static function (string $field, int $limit) use ($read, &$truncatedFields): string {
        $wasTruncated = false;
        $value = microchipsCrmIntakeLimitText(microchipsCrmIntakeText($read($field)), $limit, $wasTruncated);
        if ($wasTruncated) {
            $truncatedFields[] = $field;
        }
        return $value;
    };

    $message = $bounded('message', MICROCHIPS_CRM_INTAKE_MAX_MESSAGE_BYTES);
    if ($message === '') {
        $known = [];
        foreach ($aliases as $fieldAliases) {
            $known = array_merge($known, $fieldAliases);
        }
        $message = microchipsCrmIntakeLimitText(
            microchipsCrmIntakeAnswersMessage($answers, $known),
            MICROCHIPS_CRM_INTAKE_MAX_MESSAGE_BYTES,
            $wasTruncated
        );
        if ($wasTruncated) {
            $truncatedFields[] = 'message';
        }
    }

    $lead = [
        'name' => $bounded('name', MICROCHIPS_CRM_INTAKE_MAX_NAME_BYTES),
        'company' => $bounded('company', MICROCHIPS_CRM_INTAKE_MAX_COMPANY_BYTES),
        'phone' => $bounded('phone', MICROCHIPS_CRM_INTAKE_MAX_PHONE_BYTES),
        'email' => $bounded('email', MICROCHIPS_CRM_INTAKE_MAX_EMAIL_BYTES),
        'region' => $bounded('region', MICROCHIPS_CRM_INTAKE_MAX_REGION_BYTES),
        'product' => $bounded('product', MICROCHIPS_CRM_INTAKE_MAX_PRODUCT_BYTES),
        'message' => $message,
        'utm_source' => $bounded('utm_source', MICROCHIPS_CRM_INTAKE_MAX_UTM_BYTES),
        'utm_medium' => $bounded('utm_medium', MICROCHIPS_CRM_INTAKE_MAX_UTM_BYTES),
        'utm_campaign' => $bounded('utm_campaign', MICROCHIPS_CRM_INTAKE_MAX_UTM_BYTES),
        'landing_url' => microchipsCrmIntakeLimitText(
            microchipsCrmIntakeText($read('landing_url')),
            MICROCHIPS_CRM_INTAKE_MAX_URL_BYTES,
            $wasTruncated
        ),
    ];
    if ($wasTruncated) {
        $truncatedFields[] = 'landing_url';
    }

    $sourceUrl = microchipsCrmIntakeLimitText(
        microchipsCrmIntakeText($context['source_url'] ?? microchipsCrmIntakeAnswer($answers, $aliases['source_url'])),
        MICROCHIPS_CRM_INTAKE_MAX_URL_BYTES,
        $sourceUrlTruncated
    );
    if ($sourceUrlTruncated) {
        $truncatedFields[] = 'source_url';
    }

    $files = isset($context['files']) && is_array($context['files'])
        ? microchipsCrmIntakeNormaliseFiles($context['files'])
        : [];
    $payload = ['lead' => $lead];
    if ($sourceUrl !== '') {
        $payload['source_url'] = $sourceUrl;
    }
    if ($files !== []) {
        $payload['files'] = $files;
    }
    $requiresReview = $files !== [] || $truncatedFields !== [];

    return [
        'payload' => $payload,
        'metadata' => [
            'truncated_fields' => array_values(array_unique($truncatedFields)),
            'expected_files' => $files,
            'requires_review' => $requiresReview,
            'review_reason' => $files !== []
                ? 'form_files_require_review'
                : ($truncatedFields !== [] ? 'form_field_truncation_require_review' : null),
        ],
    ];
}

function microchipsCrmIntakeResolveSpool(array $options): string
{
    if (isset($options['spool_dir']) && is_string($options['spool_dir']) && $options['spool_dir'] !== '') {
        return microchipsCrmIntakeEnsurePrivateDirectory($options['spool_dir']);
    }

    return microchipsCrmIntakeLoadConfig(isset($options['config_path']) ? (string) $options['config_path'] : null)['spool_dir'];
}

/** @param array<int|string, mixed> $answers */
function microchipsCrmIntakeQueueBitrixResult(
    int|string $formId,
    int|string $resultId,
    array $answers,
    array $options = []
): array {
    $formId = (int) $formId;
    $resultId = (int) $resultId;
    if (!in_array($formId, MICROCHIPS_CRM_INTAKE_TARGET_FORM_IDS, true)) {
        return ['state' => 'ignored_excluded_form', 'form_id' => $formId, 'result_id' => $resultId];
    }
    if ($resultId <= 0) {
        return microchipsCrmIntakeStoreReview(
            'form_result_missing_id',
            ['form_id' => $formId, 'result_id' => $resultId, 'answers' => $answers],
            $options
        );
    }

    $built = microchipsCrmIntakeBuildFormPayload($answers, $options);
    $sourceId = 'form:' . $formId . ':result:' . $resultId;
    return microchipsCrmIntakeQueue(
        $sourceId,
        $built['payload'],
        [
            'source_type' => 'bitrix_form_result',
            'form_id' => $formId,
            'result_id' => $resultId,
            'answers' => $answers,
        ],
        microchipsCrmIntakeResolveSpool($options),
        $built['metadata']
    );
}

/**
 * Adapter for the existing CFormResult boundary.  The loader is injectable
 * for tests and for installations where the local Bitrix API wrapper differs.
 */
function microchipsCrmIntakeOnAfterResultAdd(
    int|string $webFormId,
    int|string $resultId,
    ?callable $resultLoader = null,
    array $options = []
): array {
    $webFormId = (int) $webFormId;
    $resultId = (int) $resultId;
    if (!in_array($webFormId, MICROCHIPS_CRM_INTAKE_TARGET_FORM_IDS, true)) {
        return ['state' => 'ignored_excluded_form', 'form_id' => $webFormId, 'result_id' => $resultId];
    }

    try {
        $resultLoader ??= static function (int $id): array {
            if (!class_exists('CFormResult') || !method_exists('CFormResult', 'GetDataByID')) {
                throw new RuntimeException('CFormResult::GetDataByID is unavailable');
            }
            $result = [];
            $answers = [];
            if (!CFormResult::GetDataByID($id, [], $result, $answers)) {
                throw new RuntimeException('CFormResult::GetDataByID returned no result');
            }
            return ['result' => $result, 'answers' => $answers];
        };
        $loaded = $resultLoader($resultId);
        $answers = is_array($loaded) && array_key_exists('answers', $loaded)
            ? $loaded['answers']
            : $loaded;
        if (!is_array($answers)) {
            throw new RuntimeException('form result loader must return answers array');
        }
        $options['result'] = is_array($loaded) && isset($loaded['result']) ? $loaded['result'] : [];
        return microchipsCrmIntakeQueueBitrixResult($webFormId, $resultId, $answers, $options);
    } catch (Throwable $error) {
        return microchipsCrmIntakeStoreReview(
            'form_capture_failed',
            ['form_id' => $webFormId, 'result_id' => $resultId, 'error' => $error->getMessage()],
            $options
        );
    }
}

/** @param array<string, mixed> $source */
function microchipsCrmIntakeFirst(array $source, array $keys): mixed
{
    foreach ($keys as $key) {
        if (array_key_exists($key, $source)) {
            return $source[$key];
        }
    }
    return null;
}

/** @param array<string, mixed> $snapshot */
function microchipsCrmIntakeBuildOrderPayload(array $snapshot): array
{
    $customer = is_array($snapshot['customer'] ?? null) ? $snapshot['customer'] : [];
    $contact = is_array($snapshot['contact'] ?? null) ? $snapshot['contact'] : [];
    $properties = is_array($snapshot['properties'] ?? null) ? $snapshot['properties'] : [];
    $rawProducts = $snapshot['products'] ?? ($snapshot['basket'] ?? ($snapshot['items'] ?? []));
    $products = [];
    if (is_array($rawProducts)) {
        foreach ($rawProducts as $productKey => $product) {
            if (!is_array($product)) {
                $products[] = ['name' => microchipsCrmIntakeText($product), 'quantity' => null];
                continue;
            }
            $products[] = [
                'id' => microchipsCrmIntakeText(microchipsCrmIntakeFirst($product, ['id', 'ID', 'product_id', 'PRODUCT_ID'])),
                'sku' => microchipsCrmIntakeText(microchipsCrmIntakeFirst($product, ['sku', 'SKU', 'xml_id', 'XML_ID'])),
                'name' => microchipsCrmIntakeText(microchipsCrmIntakeFirst($product, ['name', 'NAME', 'product_name', 'PRODUCT_NAME', 'title'])),
                'quantity' => microchipsCrmIntakeFirst($product, ['quantity', 'QUANTITY', 'qty']),
                'price' => microchipsCrmIntakeFirst($product, ['price', 'PRICE', 'unit_price']),
                'total' => microchipsCrmIntakeFirst($product, ['total', 'TOTAL', 'sum', 'SUM']),
                'key' => (string) $productKey,
            ];
        }
    }
    $totals = is_array($snapshot['totals'] ?? null) ? $snapshot['totals'] : [];
    $delivery = $snapshot['delivery'] ?? ($snapshot['delivery_service'] ?? null);
    $comment = microchipsCrmIntakeText(microchipsCrmIntakeFirst($snapshot, ['comment', 'COMMENT', 'user_description', 'description']));
    $orderId = microchipsCrmIntakeText(microchipsCrmIntakeFirst($snapshot, ['order_id', 'ORDER_ID', 'id', 'ID']));

    $name = microchipsCrmIntakeText(microchipsCrmIntakeFirst($customer, ['name', 'NAME', 'full_name']))
        ?: microchipsCrmIntakeText(microchipsCrmIntakeFirst($contact, ['name', 'NAME', 'full_name']))
        ?: microchipsCrmIntakeText(microchipsCrmIntakeFirst($snapshot, ['name', 'NAME']));
    $company = microchipsCrmIntakeText(microchipsCrmIntakeFirst($customer, ['company', 'COMPANY', 'company_name']))
        ?: microchipsCrmIntakeText(microchipsCrmIntakeFirst($contact, ['company', 'COMPANY', 'company_name']))
        ?: microchipsCrmIntakeText(microchipsCrmIntakeFirst($snapshot, ['company', 'COMPANY']));
    $phone = microchipsCrmIntakeText(microchipsCrmIntakeFirst($contact, ['phone', 'PHONE', 'tel']))
        ?: microchipsCrmIntakeText(microchipsCrmIntakeFirst($customer, ['phone', 'PHONE', 'tel']))
        ?: microchipsCrmIntakeText(microchipsCrmIntakeFirst($snapshot, ['phone', 'PHONE']));
    $email = microchipsCrmIntakeText(microchipsCrmIntakeFirst($contact, ['email', 'EMAIL', 'mail']))
        ?: microchipsCrmIntakeText(microchipsCrmIntakeFirst($customer, ['email', 'EMAIL', 'mail']))
        ?: microchipsCrmIntakeText(microchipsCrmIntakeFirst($snapshot, ['email', 'EMAIL']));
    $region = microchipsCrmIntakeText(microchipsCrmIntakeFirst($contact, ['region', 'REGION', 'city']))
        ?: microchipsCrmIntakeText(microchipsCrmIntakeFirst($snapshot, ['region', 'REGION', 'city']));
    $productNames = [];
    foreach ($products as $product) {
        $productName = trim((string) ($product['name'] ?? ''));
        if ($productName !== '') {
            $productNames[] = $productName;
        }
    }
    $product = implode(', ', $productNames);

    $messageData = [
        'order_id' => $orderId,
        'customer' => microchipsCrmIntakeSanitiseRaw($customer),
        'contact' => microchipsCrmIntakeSanitiseRaw($contact),
        'properties' => microchipsCrmIntakeSanitiseRaw($properties),
        'products' => microchipsCrmIntakeSanitiseRaw($products),
        'totals' => microchipsCrmIntakeSanitiseRaw($totals),
        'delivery' => microchipsCrmIntakeSanitiseRaw($delivery),
        'comment' => $comment,
    ];
    $message = microchipsCrmIntakeJsonEncode($messageData);
    $truncated = false;
    $message = microchipsCrmIntakeLimitText($message, MICROCHIPS_CRM_INTAKE_MAX_MESSAGE_BYTES, $truncated);
    $product = microchipsCrmIntakeLimitText($product, MICROCHIPS_CRM_INTAKE_MAX_PRODUCT_BYTES, $productTruncated);
    $landingUrl = microchipsCrmIntakeLimitText(
        microchipsCrmIntakeText(microchipsCrmIntakeFirst($snapshot, ['landing_url', 'LANDING_URL', 'url', 'URL'])),
        MICROCHIPS_CRM_INTAKE_MAX_URL_BYTES,
        $urlTruncated
    );
    $sourceUrl = microchipsCrmIntakeLimitText(
        microchipsCrmIntakeText(microchipsCrmIntakeFirst($snapshot, ['source_url', 'SOURCE_URL', 'original_url', 'ORIGINAL_URL'])),
        MICROCHIPS_CRM_INTAKE_MAX_URL_BYTES,
        $sourceUrlTruncated
    );
    $files = is_array($snapshot['files'] ?? null) ? microchipsCrmIntakeNormaliseFiles($snapshot['files']) : [];

    $lead = [
        'name' => microchipsCrmIntakeLimitText($name, MICROCHIPS_CRM_INTAKE_MAX_NAME_BYTES),
        'company' => microchipsCrmIntakeLimitText($company, MICROCHIPS_CRM_INTAKE_MAX_COMPANY_BYTES),
        'phone' => microchipsCrmIntakeLimitText($phone, MICROCHIPS_CRM_INTAKE_MAX_PHONE_BYTES),
        'email' => microchipsCrmIntakeLimitText($email, MICROCHIPS_CRM_INTAKE_MAX_EMAIL_BYTES),
        'region' => microchipsCrmIntakeLimitText($region, MICROCHIPS_CRM_INTAKE_MAX_REGION_BYTES),
        'product' => $product,
        'message' => $message,
        'utm_source' => microchipsCrmIntakeLimitText(microchipsCrmIntakeText(microchipsCrmIntakeFirst($snapshot, ['utm_source', 'UTM_SOURCE'])), MICROCHIPS_CRM_INTAKE_MAX_UTM_BYTES),
        'utm_medium' => microchipsCrmIntakeLimitText(microchipsCrmIntakeText(microchipsCrmIntakeFirst($snapshot, ['utm_medium', 'UTM_MEDIUM'])), MICROCHIPS_CRM_INTAKE_MAX_UTM_BYTES),
        'utm_campaign' => microchipsCrmIntakeLimitText(microchipsCrmIntakeText(microchipsCrmIntakeFirst($snapshot, ['utm_campaign', 'UTM_CAMPAIGN'])), MICROCHIPS_CRM_INTAKE_MAX_UTM_BYTES),
        'landing_url' => $landingUrl,
    ];
    $payload = ['lead' => $lead];
    if ($sourceUrl !== '') {
        $payload['source_url'] = $sourceUrl;
    }
    if ($files !== []) {
        $payload['files'] = $files;
    }

    $truncatedFields = [];
    if ($truncated) {
        $truncatedFields[] = 'message';
    }
    if ($productTruncated) {
        $truncatedFields[] = 'product';
    }
    if ($urlTruncated) {
        $truncatedFields[] = 'landing_url';
    }
    if ($sourceUrlTruncated) {
        $truncatedFields[] = 'source_url';
    }
    $requiresReview = $files !== [] || $truncatedFields !== [];

    return [
        'order_id' => $orderId,
        'payload' => $payload,
        'metadata' => [
            'truncated_fields' => $truncatedFields,
            'expected_files' => $files,
            'requires_review' => $requiresReview,
            'review_reason' => $files !== []
                ? 'order_files_require_review'
                : ($truncatedFields !== [] ? 'order_field_truncation_require_review' : null),
        ],
    ];
}

/** @param array<string, mixed> $eventParameters */
function microchipsCrmIntakeQueueSaleOrder(array $eventParameters, array $options = []): array
{
    $isNew = $eventParameters['IS_NEW'] ?? false;
    $isNew = $isNew === true || $isNew === 1 || $isNew === '1' || strtoupper((string) $isNew) === 'Y';
    if (!$isNew) {
        return ['state' => 'ignored_existing_order'];
    }

    $entity = $eventParameters['ENTITY'] ?? null;
    try {
        $snapshotter = $options['snapshotter'] ?? null;
        if (is_callable($snapshotter)) {
            $snapshot = $snapshotter($entity);
        } elseif (is_array($entity)) {
            $snapshot = $entity;
        } else {
            throw new RuntimeException('ENTITY requires an injected local Bitrix snapshotter');
        }
        if (!is_array($snapshot)) {
            throw new RuntimeException('order snapshotter must return an array');
        }
        $built = microchipsCrmIntakeBuildOrderPayload($snapshot);
        if (!preg_match('/\A\d+\z/', $built['order_id']) || (int) $built['order_id'] <= 0) {
            throw new RuntimeException('order snapshot has no positive order ID');
        }
        $sourceId = 'order:' . (int) $built['order_id'];
        return microchipsCrmIntakeQueue(
            $sourceId,
            $built['payload'],
            [
                'source_type' => 'bitrix_sale_order',
                'event_parameters' => $eventParameters,
                'snapshot' => $snapshot,
            ],
            microchipsCrmIntakeResolveSpool($options),
            $built['metadata']
        );
    } catch (Throwable $error) {
        return microchipsCrmIntakeStoreReview(
            'order_capture_failed',
            ['source_type' => 'bitrix_sale_order', 'event_parameters' => $eventParameters, 'entity' => $entity, 'error' => $error->getMessage()],
            $options
        );
    }
}

/**
 * Stable name for the operator's OnSaleOrderSaved adapter.  The adapter takes
 * the already verified ENTITY/IS_NEW event parameters so this file does not
 * guess a Bitrix vendor Event API that is unavailable in this checkout.
 *
 * @param array<string, mixed> $eventParameters
 */
function microchipsCrmIntakeOnSaleOrderSaved(array $eventParameters, array $options = []): array
{
    return microchipsCrmIntakeQueueSaleOrder($eventParameters, $options);
}

/** @param array<string, mixed> $rawSource */
function microchipsCrmIntakeStoreReview(string $reason, array $rawSource, array $options = []): array
{
    $spoolDir = microchipsCrmIntakeResolveSpool($options);
    $reviewKey = 'capture-review-' . bin2hex(random_bytes(10));
    $envelope = [
        'schema' => 1,
        'namespace' => MICROCHIPS_CRM_INTAKE_NAMESPACE,
        'source_id' => null,
        'delivery_id' => null,
        'payload_sha256' => null,
        'request' => null,
        'request_json' => null,
        'raw_source' => microchipsCrmIntakeSanitiseRaw($rawSource),
        'metadata' => ['requires_review' => true, 'review_reason' => $reason],
        'created_at' => microchipsCrmIntakeNow(),
    ];
    $path = $spoolDir . DIRECTORY_SEPARATOR . 'review' . DIRECTORY_SEPARATOR . $reviewKey . '.json';
    microchipsCrmIntakeAtomicCreate($path, microchipsCrmIntakeJsonEncode($envelope) . "\n");
    microchipsCrmIntakeWriteStatus($spoolDir, $reviewKey, [
        'schema' => 1,
        'status_key' => $reviewKey,
        'state' => 'failed_review',
        'review_reason' => $reason,
        'attempts' => 0,
        'created_at' => microchipsCrmIntakeNow(),
        'updated_at' => microchipsCrmIntakeNow(),
    ]);

    return ['state' => 'failed_review', 'review_reason' => $reason, 'path' => $path];
}

/** @param list<string> $headers */
function microchipsCrmIntakeCurlRequest(string $method, string $url, array $headers, ?string $body = null): array
{
    if (!function_exists('curl_init')) {
        throw new RuntimeException('PHP cURL extension is required for production delivery');
    }
    $curl = curl_init($url);
    if ($curl === false) {
        throw new RuntimeException('curl_init failed');
    }
    $options = [
        CURLOPT_CUSTOMREQUEST => $method,
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 5,
        CURLOPT_TIMEOUT => 20,
        CURLOPT_FOLLOWLOCATION => false,
        CURLOPT_HEADER => false,
    ];
    if ($body !== null) {
        $options[CURLOPT_POSTFIELDS] = $body;
    }
    curl_setopt_array($curl, $options);
    $responseBody = curl_exec($curl);
    $error = curl_error($curl);
    $httpCode = (int) curl_getinfo($curl, CURLINFO_RESPONSE_CODE);
    curl_close($curl);
    if ($responseBody === false) {
        throw new RuntimeException('curl request failed: ' . ($error !== '' ? $error : 'unknown error'));
    }

    return ['http_code' => $httpCode, 'body' => (string) $responseBody];
}

function microchipsCrmIntakePerformRequest(
    string $method,
    string $url,
    string $token,
    ?string $body = null,
    ?callable $transport = null
): array {
    $headers = [
        'Accept: application/json',
        'Content-Type: application/json',
        'X-Intake-Token: ' . $token,
    ];
    $transport ??= 'microchipsCrmIntakeCurlRequest';
    $response = $transport($method, $url, $headers, $body);
    if (!is_array($response)) {
        throw new RuntimeException('transport must return response array');
    }
    $httpCode = (int) ($response['http_code'] ?? 0);
    $responseBody = $response['body'] ?? null;
    $data = is_array($responseBody)
        ? $responseBody
        : microchipsCrmIntakeJsonDecode((string) $responseBody);

    return ['http_code' => $httpCode, 'data' => $data];
}

/** @param list<array<string, mixed>> $expectedFiles */
function microchipsCrmIntakeValidateReceipt(
    array $data,
    string $sourceId,
    string $payloadHash,
    array $expectedFiles,
    int $httpCode,
    bool $requireDelivered = false
): array {
    $status = strtolower(trim((string) ($data['status'] ?? '')));
    if (!in_array($status, ['queued', 'delivered', 'failed', 'unavailable'], true)) {
        throw new RuntimeException('receiver response has unknown status');
    }
    foreach (['receipt_id', 'source_id', 'delivery_id', 'namespace', 'identity_namespace', 'payload_sha256'] as $field) {
        if (!isset($data[$field]) || (string) $data[$field] === '') {
            throw new RuntimeException('receiver response misses ' . $field);
        }
    }
    if ((string) $data['source_id'] !== $sourceId || (string) $data['delivery_id'] !== $sourceId) {
        throw new RuntimeException('receiver response identity mismatch');
    }
    if ((string) $data['namespace'] !== MICROCHIPS_CRM_INTAKE_NAMESPACE
        || (string) $data['identity_namespace'] !== MICROCHIPS_CRM_INTAKE_NAMESPACE) {
        throw new RuntimeException('receiver response namespace identity mismatch');
    }
    if (!hash_equals($payloadHash, (string) $data['payload_sha256'])) {
        throw new RuntimeException('receiver response payload hash mismatch');
    }
    if (in_array($status, ['queued', 'delivered'], true) && $httpCode >= 400) {
        throw new RuntimeException('successful receiver status returned with HTTP error');
    }
    if ($requireDelivered && $status !== 'delivered') {
        throw new RuntimeException('receipt GET did not confirm delivered');
    }
    $responseFiles = $data['files'] ?? [];
    if (!is_array($responseFiles)) {
        throw new RuntimeException('receiver response files must be an array');
    }
    if ($status === 'delivered') {
        $leadId = $data['lead_id'] ?? null;
        $leadIdText = is_int($leadId) || is_string($leadId) ? (string) $leadId : '';
        if (!preg_match('/\A[1-9][0-9]*\z/', $leadIdText)) {
            throw new RuntimeException('delivered response has no positive lead_id');
        }
        if (count($responseFiles) !== count($expectedFiles)) {
            throw new RuntimeException('delivered response file count mismatch');
        }
        $matched = [];
        foreach ($expectedFiles as $expected) {
            $expectedId = (string) ($expected['file_id'] ?? ($expected['id'] ?? ''));
            $expectedName = (string) ($expected['filename'] ?? ($expected['name'] ?? ''));
            $expectedSha = strtolower((string) ($expected['sha256'] ?? ''));
            if ($expectedId === '' || !preg_match('/\A[a-f0-9]{64}\z/', $expectedSha)) {
                throw new RuntimeException('expected delivered file lacks file_id or SHA');
            }
            $found = false;
            foreach ($responseFiles as $responseIndex => $responseFile) {
                if (!is_array($responseFile)) {
                    continue;
                }
                if (isset($matched[$responseIndex])) {
                    continue;
                }
                $responseId = (string) ($responseFile['file_id'] ?? ($responseFile['id'] ?? ''));
                $responseName = (string) ($responseFile['filename'] ?? ($responseFile['name'] ?? ''));
                $responseStatus = strtolower((string) ($responseFile['status'] ?? 'delivered'));
                if ($responseId !== $expectedId) {
                    continue;
                }
                if ($expectedName !== '' && $responseName !== $expectedName) {
                    throw new RuntimeException('delivered response file name mismatch');
                }
                if (in_array($responseStatus, ['missing', 'failed', 'unavailable', 'rejected'], true)) {
                    throw new RuntimeException('delivered response has a failed expected file');
                }
                $attachmentId = $responseFile['attachment_id'] ?? null;
                $attachmentText = is_int($attachmentId) || is_string($attachmentId) ? (string) $attachmentId : '';
                if (!preg_match('/\A[1-9][0-9]*\z/', $attachmentText)) {
                    throw new RuntimeException('delivered response file has no positive attachment_id');
                }
                $responseSha = strtolower((string) ($responseFile['sha256'] ?? ''));
                if (!preg_match('/\A[a-f0-9]{64}\z/', $responseSha)
                    || !hash_equals($expectedSha, $responseSha)) {
                    throw new RuntimeException('delivered response file SHA mismatch');
                }
                $matched[$responseIndex] = true;
                $found = true;
                break;
            }
            if (!$found) {
                throw new RuntimeException('delivered response is missing an expected file');
            }
        }
    }

    return [
        'status' => $status,
        'receipt_id' => (string) $data['receipt_id'],
        'source_id' => (string) $data['source_id'],
        'delivery_id' => (string) $data['delivery_id'],
        'namespace' => (string) $data['namespace'],
        'payload_sha256' => (string) $data['payload_sha256'],
        'identity_namespace' => (string) $data['identity_namespace'],
        'lead_id' => isset($data['lead_id']) ? (string) $data['lead_id'] : null,
        'files' => microchipsCrmIntakeSanitiseRaw($responseFiles),
    ];
}

function microchipsCrmIntakeRetryDelay(int $attempts): int
{
    return min(3600, max(10, 2 ** min(10, max(0, $attempts - 1))));
}

function microchipsCrmIntakeMove(string $path, string $spoolDir, string $directory, ?callable $syncDirectory = null): string
{
    microchipsCrmIntakeAssertNoSymlink($path);
    $target = $spoolDir . DIRECTORY_SEPARATOR . $directory . DIRECTORY_SEPARATOR . basename($path);
    microchipsCrmIntakeAssertNoSymlink($target);
    if ($path === $target) {
        return $target;
    }
    $sourceDirectory = dirname($path);
    $targetDirectory = dirname($target);
    if (file_exists($target)) {
        $sourceStat = @stat($path);
        $targetStat = @stat($target);
        $sameFile = is_array($sourceStat) && is_array($targetStat)
            && ($sourceStat['dev'] ?? null) === ($targetStat['dev'] ?? null)
            && ($sourceStat['ino'] ?? null) === ($targetStat['ino'] ?? null);
        if (!$sameFile) {
            throw new RuntimeException('destination spool file already exists');
        }
        // A prior move may have published the hard-link and then failed while
        // syncing the source directory.  Remove only that exact stale link;
        // the pending name remains the retry source.
        if (!@unlink($target)) {
            throw new RuntimeException('cannot remove stale spool move link');
        }
        microchipsCrmIntakeSyncDirectory($targetDirectory, $syncDirectory);
    }
    // Hard-link first so a directory fsync failure cannot remove the only
    // pending name.  All state directories are created under one spool root.
    if (!function_exists('link') || !@link($path, $target)) {
        throw new RuntimeException('cannot create durable spool move link');
    }
    @chmod($target, 0600);
    try {
        microchipsCrmIntakeSyncDirectory($targetDirectory, $syncDirectory);
        if (!@unlink($path)) {
            throw new RuntimeException('cannot remove old spool move name');
        }
        if ($sourceDirectory !== $targetDirectory) {
            microchipsCrmIntakeSyncDirectory($sourceDirectory, $syncDirectory);
        }
    } catch (Throwable $error) {
        // Keep a pending name available for retry.  The best-effort relink is
        // safe because source/target are inside the same private spool.
        if (!is_file($path) && is_file($target)) {
            @link($target, $path);
        }
        throw $error;
    }
    return $target;
}

/**
 * Process each pending item once under one process-wide flock.  Failed and
 * unavailable deliveries remain pending with a durable retry time; queued and
 * delivered raw envelopes move to done and are retained there.
 */
function microchipsCrmIntakeConsume(
    string $spoolDir,
    string $token,
    ?callable $transport = null,
    int $limit = 100,
    bool $force = false
): array {
    $spoolDir = microchipsCrmIntakeEnsurePrivateDirectory($spoolDir);
    $limit = max(1, $limit);
    $lockPath = $spoolDir . DIRECTORY_SEPARATOR . '.consumer.lock';
    microchipsCrmIntakeAssertNoSymlink($lockPath);
    $lock = @fopen($lockPath, 'c+b');
    if ($lock === false) {
        throw new RuntimeException('Cannot open consumer lock');
    }
    @chmod($lockPath, 0600);
    if (!flock($lock, LOCK_EX | LOCK_NB)) {
        fclose($lock);
        return ['state' => 'busy', 'processed' => 0, 'errors' => 0, 'items' => []];
    }

    $items = [];
    $errors = 0;
    try {
        $paths = glob($spoolDir . DIRECTORY_SEPARATOR . 'pending' . DIRECTORY_SEPARATOR . '*.json') ?: [];
        sort($paths, SORT_STRING);
        $processed = 0;
        foreach ($paths as $path) {
            if ($processed >= $limit) {
                break;
            }
            $processed++;
            $sourceId = '';
            $status = [];
            $response = [];
            $validated = [];
            try {
                $envelope = microchipsCrmIntakeJsonDecode((string) file_get_contents($path));
                $sourceId = (string) ($envelope['source_id'] ?? '');
                microchipsCrmIntakeValidateSourceId($sourceId);
                $status = microchipsCrmIntakeReadStatus($spoolDir, $sourceId) ?? [];
                $metadata = is_array($envelope['metadata'] ?? null) ? $envelope['metadata'] : [];
                $statusState = (string) ($status['state'] ?? 'spooled');
                if (in_array($statusState, ['queued', 'delivered'], true)) {
                    microchipsCrmIntakeMove($path, $spoolDir, 'done');
                    $items[] = ['source_id' => $sourceId, 'state' => $statusState, 'action' => 'retained_done'];
                    continue;
                }
                if (!empty($metadata['requires_review'])) {
                    microchipsCrmIntakeUpdateStatus($spoolDir, $sourceId, [
                        'state' => 'failed_review',
                        'review_reason' => (string) ($metadata['review_reason'] ?? 'manual_review_required'),
                    ]);
                    microchipsCrmIntakeMove($path, $spoolDir, 'review');
                    $items[] = ['source_id' => $sourceId, 'state' => 'failed_review', 'action' => 'retained_review'];
                    continue;
                }
                $nextRetryAt = (string) ($status['next_retry_at'] ?? '');
                if (!$force && $nextRetryAt !== '' && strtotime($nextRetryAt) > time()) {
                    $items[] = ['source_id' => $sourceId, 'state' => 'deferred', 'next_retry_at' => $nextRetryAt];
                    continue;
                }
                $attempts = (int) ($status['attempts'] ?? 0) + 1;
                microchipsCrmIntakeUpdateStatus($spoolDir, $sourceId, [
                    'state' => 'processing',
                    'attempts' => $attempts,
                    'last_error' => null,
                ]);
                $requestJson = (string) ($envelope['request_json'] ?? '');
                if ($requestJson === '') {
                    throw new RuntimeException('immutable request_json is missing');
                }
                $response = microchipsCrmIntakePerformRequest(
                    'POST',
                    MICROCHIPS_CRM_INTAKE_ENDPOINT,
                    $token,
                    $requestJson,
                    $transport
                );
                $expectedFiles = is_array($metadata['expected_files'] ?? null) ? $metadata['expected_files'] : [];
                $validated = microchipsCrmIntakeValidateReceipt(
                    $response['data'],
                    $sourceId,
                    (string) ($envelope['payload_sha256'] ?? ''),
                    $expectedFiles,
                    (int) $response['http_code']
                );
                $remoteState = $validated['status'];
                if ($remoteState === 'delivered') {
                    // POST delivered is only an intermediate acknowledgement.
                    // The receiver's GET performs the durable lead/attachment
                    // check before this envelope may leave pending.
                    $validated = microchipsCrmIntakeGetReceipt(
                        $validated['receipt_id'],
                        $token,
                        $transport,
                        $sourceId,
                        (string) ($envelope['payload_sha256'] ?? ''),
                        $expectedFiles
                    );
                    $remoteState = $validated['status'];
                }
                $patch = [
                    'state' => $remoteState,
                    'remote_status' => $remoteState,
                    'receipt_id' => $validated['receipt_id'],
                    'lead_id' => $validated['lead_id'],
                    'files' => $validated['files'],
                    'last_http_code' => (int) $response['http_code'],
                    'last_error' => null,
                    'next_retry_at' => null,
                ];
                microchipsCrmIntakeUpdateStatus($spoolDir, $sourceId, $patch);
                if (in_array($remoteState, ['queued', 'delivered'], true)) {
                    microchipsCrmIntakeMove($path, $spoolDir, 'done');
                } else {
                    $errors++;
                    $patch['next_retry_at'] = gmdate('c', time() + microchipsCrmIntakeRetryDelay($attempts));
                    microchipsCrmIntakeUpdateStatus($spoolDir, $sourceId, $patch);
                }
                $items[] = ['source_id' => $sourceId, 'state' => $remoteState, 'receipt_id' => $validated['receipt_id']];
            } catch (Throwable $error) {
                $errors++;
                $sourceId = isset($sourceId) && $sourceId !== '' ? $sourceId : 'unknown';
                $attempts = (int) (($status['attempts'] ?? 0) + 1);
                $message = $error->getMessage();
                if ($token !== '') {
                    $message = str_replace($token, '[redacted]', $message);
                }
                if ($sourceId !== 'unknown') {
                    $errorPatch = [
                        'state' => 'transport_or_validation_error',
                        'attempts' => $attempts,
                        'last_http_code' => isset($response['http_code']) ? (int) $response['http_code'] : null,
                        'last_error' => microchipsCrmIntakeLimitText($message, 2000),
                        'next_retry_at' => gmdate('c', time() + microchipsCrmIntakeRetryDelay($attempts)),
                    ];
                    if (isset($validated['receipt_id'])) {
                        $errorPatch['receipt_id'] = $validated['receipt_id'];
                        $errorPatch['remote_status'] = $validated['status'] ?? null;
                        $errorPatch['lead_id'] = $validated['lead_id'] ?? null;
                        $errorPatch['files'] = $validated['files'] ?? [];
                    }
                    microchipsCrmIntakeUpdateStatus($spoolDir, $sourceId, $errorPatch);
                    $items[] = ['source_id' => $sourceId, 'state' => 'retry_pending', 'error' => microchipsCrmIntakeLimitText($message, 2000)];
                } else {
                    $items[] = ['state' => 'malformed_pending', 'error' => microchipsCrmIntakeLimitText($message, 2000), 'path' => $path];
                }
            }
            unset($sourceId, $status, $response);
        }
    } finally {
        flock($lock, LOCK_UN);
        fclose($lock);
    }

    return ['state' => 'completed', 'processed' => count($items), 'errors' => $errors, 'items' => $items];
}

function microchipsCrmIntakeGetReceipt(
    string $receiptId,
    string $token,
    ?callable $transport = null,
    ?string $sourceId = null,
    ?string $payloadHash = null,
    array $expectedFiles = []
): array {
    if ($receiptId === '' || strlen($receiptId) > 256 || !preg_match('/\A[A-Za-z0-9._:-]+\z/', $receiptId)) {
        throw new InvalidArgumentException('invalid receipt_id');
    }
    $url = MICROCHIPS_CRM_INTAKE_ENDPOINT . '/receipts/' . rawurlencode($receiptId);
    $response = microchipsCrmIntakePerformRequest('GET', $url, $token, null, $transport);
    $data = $response['data'];
    if (!isset($data['receipt_id']) || (string) $data['receipt_id'] !== $receiptId) {
        throw new RuntimeException('receipt response identity mismatch');
    }
    if ($sourceId !== null) {
        if ($payloadHash === null || $payloadHash === '') {
            throw new InvalidArgumentException('payload hash is required for receipt verification');
        }
        return microchipsCrmIntakeValidateReceipt(
            $data,
            $sourceId,
            $payloadHash,
            $expectedFiles,
            (int) $response['http_code'],
            true
        );
    }
    if ((int) $response['http_code'] >= 400) {
        throw new RuntimeException('receipt GET returned HTTP error');
    }
    return microchipsCrmIntakeSanitiseRaw($data);
}

/** @param list<string> $arguments */
function microchipsCrmIntakeCli(array $arguments): int
{
    $command = $arguments[0] ?? 'consume';
    $configPath = null;
    $limit = 100;
    $force = false;
    for ($index = 1, $count = count($arguments); $index < $count; $index++) {
        $argument = $arguments[$index];
        if ($argument === '--force') {
            $force = true;
            continue;
        }
        if ($argument === '--config' && isset($arguments[$index + 1])) {
            $configPath = $arguments[++$index];
            continue;
        }
        if (str_starts_with($argument, '--config=')) {
            $configPath = substr($argument, 9);
            continue;
        }
        if (str_starts_with($argument, '--limit=')) {
            $limit = max(1, (int) substr($argument, 8));
        }
    }

    if ($command !== 'consume') {
        fwrite(STDERR, "Usage: php microchips_crm_intake.php consume [--config PATH] [--limit=N] [--force]\n");
        return 64;
    }

    try {
        $config = microchipsCrmIntakeLoadConfig($configPath);
        $result = microchipsCrmIntakeConsume($config['spool_dir'], $config['token'], null, $limit, $force);
        foreach ($result['items'] as $item) {
            fwrite(STDOUT, microchipsCrmIntakeJsonEncode($item) . "\n");
        }
        return ($result['state'] === 'busy' || (int) $result['errors'] > 0) ? 1 : 0;
    } catch (Throwable $error) {
        fwrite(STDERR, 'intake consumer failed: ' . microchipsCrmIntakeLimitText($error->getMessage(), 2000) . "\n");
        return 1;
    }
}

if (
    PHP_SAPI === 'cli'
    && isset($_SERVER['SCRIPT_FILENAME'])
    && realpath((string) $_SERVER['SCRIPT_FILENAME']) === realpath(__FILE__)
) {
    exit(microchipsCrmIntakeCli(array_slice($argv, 1)));
}
