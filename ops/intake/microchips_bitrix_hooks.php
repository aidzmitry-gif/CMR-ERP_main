<?php
declare(strict_types=1);

/** Native Bitrix bridge. Require after the producer, then explicitly register.
 * Vendor contracts verified on microchips.by 2026-09-07:
 * sale/lib/orderbase.php:1392, eventactions.php:17, entitypropertyvalue.php:799/972,
 * main/lib/eventmanager.php:103. No network or source mutation in these hooks.
 */
const MICROCHIPS_CRM_INTAKE_NATIVE_QUICKBUY_SCRIPT = '/home/user/web/_shared/bitrix/components/aspro/oneclickbuy.max/script.php';

function microchipsCrmIntakeNativeOrderSnapshot(object $order): array
{
    $fields = $order->getFieldValues();
    $properties = [];
    $contact = [];
    $files = [];
    $mapping = [
        'FIO' => 'name', 'NAME' => 'name', 'CONTACT_PERSON' => 'name',
        'PHONE' => 'phone', 'EMAIL' => 'email', 'COMPANY' => 'company',
        'COMPANY_NAME' => 'company', 'CITY' => 'region',
    ];
    foreach ($order->getPropertyCollection() as $property) {
        $meta = $property->getProperty();
        $value = $property->getValue();
        $code = (string) ($meta['CODE'] ?? '');
        $properties[] = ['code' => $code, 'name' => (string) ($meta['NAME'] ?? ''), 'value' => $value];
        if (isset($mapping[$code]) && $value !== null && $value !== '') {
            $contact[$mapping[$code]] = $value;
        }
        if (($meta['TYPE'] ?? '') === 'FILE' && $value) {
            foreach ((array) $value as $id) {
                $files[] = ['id' => (string) $id, 'status' => 'source_file_requires_review'];
            }
        }
    }
    $products = [];
    foreach ($order->getBasket() as $item) {
        $f = $item->getFieldValues();
        $products[] = array_intersect_key($f, array_flip(['PRODUCT_ID', 'NAME', 'XML_ID', 'QUANTITY', 'PRICE', 'CURRENCY']));
    }
    return [
        'order_id' => (int) $order->getId(), 'contact' => $contact,
        'properties' => $properties, 'products' => $products, 'files' => $files,
        'totals' => array_intersect_key($fields, array_flip(['PRICE', 'CURRENCY', 'PRICE_DELIVERY', 'DISCOUNT_VALUE'])),
        'delivery' => ['id' => $fields['DELIVERY_ID'] ?? null],
        'comment' => (string) ($fields['USER_DESCRIPTION'] ?? ''),
        'landing_url' => 'https://microchips.by/basket/',
    ];
}

/** @return array<string, mixed> */
function microchipsCrmIntakeNativeQuickBuyRequestContext(
    mixed $method,
    mixed $script,
    mixed $requestSiteId,
    mixed $requestPersonTypeId,
    bool $oneClickBuyIsArray,
    bool $contactPersonPresent,
    mixed $contactPerson
): array {
    $scriptMatches = is_string($script)
        && (str_replace('\\', '/', $script) === MICROCHIPS_CRM_INTAKE_NATIVE_QUICKBUY_SCRIPT
            || realpath($script) === MICROCHIPS_CRM_INTAKE_NATIVE_QUICKBUY_SCRIPT);
    if ($method !== 'POST' || !is_string($script)
        || !$scriptMatches
        || !is_scalar($requestSiteId) || (string) $requestSiteId !== 's1'
        || !is_scalar($requestPersonTypeId) || (string) $requestPersonTypeId !== '2'
        || !$oneClickBuyIsArray) {
        return ['active' => false];
    }

    $context = [
        'active' => true,
        'method' => 'POST',
        'script' => MICROCHIPS_CRM_INTAKE_NATIVE_QUICKBUY_SCRIPT,
        'request_site_id' => 's1',
        'request_person_type_id' => 2,
        'contact_person_present' => $contactPersonPresent,
        'contact_person_source' => 'POST[ONE_CLICK_BUY][CONTACT_PERSON]',
        'has_value' => false,
        'review_required' => false,
    ];
    if (!$contactPersonPresent || $contactPerson === null) {
        return $context;
    }

    if (!is_scalar($contactPerson)) {
        $context['review_required'] = true;
        $context['review_reason'] = 'contact_person_not_scalar';
        $context['contact_person_type'] = get_debug_type($contactPerson);
        return $context;
    }
    $selected = (string) $contactPerson;
    $context += ['contact_person' => $selected, 'contact_person_type' => get_debug_type($contactPerson),
        'contact_person_bytes' => strlen($selected), 'contact_person_sha256' => hash('sha256', $selected)];
    if (is_string($contactPerson) && preg_match('//u', $selected) !== 1) {
        $context['review_required'] = true;
        $context['review_reason'] = 'contact_person_invalid_utf8';
        return $context;
    }
    $context['has_value'] = trim($selected) !== '';
    return $context;
}

/** @return array<string, mixed> */
function microchipsCrmIntakeNativeQuickBuyOrderContext(object $order): array
{
    try {
        if (!method_exists($order, 'getId') || !method_exists($order, 'getFieldValues')
            || !method_exists($order, 'getPropertyCollection')) {
            return ['active' => false];
        }
        $rawId = $order->getId();
        if (!(is_int($rawId) || (is_string($rawId) && preg_match('/\A\d+\z/', $rawId))) || (int) $rawId <= 0) {
            return ['active' => false];
        }
        $fields = $order->getFieldValues();
        if (!is_array($fields) || !is_scalar($fields['LID'] ?? null) || (string) $fields['LID'] !== 's1'
            || !is_scalar($fields['PERSON_TYPE_ID'] ?? null) || (string) $fields['PERSON_TYPE_ID'] !== '2') {
            return ['active' => false];
        }
        $properties = $order->getPropertyCollection();
        if (!is_iterable($properties)) {
            return ['active' => false];
        }
        foreach ($properties as $property) {
            if (!is_object($property) || !method_exists($property, 'getProperty')) continue;
            $meta = $property->getProperty();
            if (is_array($meta) && strtoupper((string) ($meta['CODE'] ?? '')) === 'CONTACT_PERSON'
                && strtoupper((string) ($meta['TYPE'] ?? '')) === 'STRING') {
                return ['active' => true, 'order_id' => (int) $rawId, 'order_lid' => 's1',
                    'order_person_type_id' => 2,
                    'contact_person_property' => ['code' => 'CONTACT_PERSON', 'type' => 'STRING']];
            }
        }
    } catch (Throwable) {
        // A vendor boundary mismatch must not turn an ordinary order into a
        // quick-buy review.  The established producer will capture/review it.
    }
    return ['active' => false];
}

/** @return array<string, mixed> */
function microchipsCrmIntakeNativeQuickBuyReviewContext(array $context): array
{
    $review = array_intersect_key($context, array_flip([
        'method', 'script', 'request_site_id', 'request_person_type_id',
        'order_id', 'order_lid', 'order_person_type_id', 'contact_person_property',
        'contact_person_present', 'contact_person_source', 'contact_person_type',
        'contact_person_bytes', 'contact_person_sha256',
    ]));
    if (isset($context['contact_person']) && is_string($context['contact_person'])
        && preg_match('//u', $context['contact_person']) === 1) {
        $review['contact_person'] = $context['contact_person'];
    }
    if (isset($context['review_reason'])) {
        $review['review_reason'] = (string) $context['review_reason'];
    }
    return $review;
}

/** @param array<string, mixed> $snapshot @param array<string, mixed> $context */
function microchipsCrmIntakeNativeEnrichQuickBuySnapshot(array $snapshot, array $context): array
{
    $review = static fn (string $reason): array => ['state' => 'review', 'reason' => $reason, 'snapshot' => $snapshot];
    if (!($context['active'] ?? false)) {
        return ['state' => 'skipped', 'snapshot' => $snapshot];
    }
    if (($context['review_required'] ?? false) === true) {
        return $review((string) ($context['review_reason'] ?? 'contact_person_invalid'));
    }
    if (!($context['has_value'] ?? false)) {
        return ['state' => 'unchanged', 'snapshot' => $snapshot];
    }

    $selected = (string) ($context['contact_person'] ?? '');
    if (strlen($selected) > MICROCHIPS_CRM_INTAKE_MAX_NAME_BYTES) {
        return $review('contact_person_over_limit');
    }
    if (preg_match('//u', $selected) !== 1) {
        return $review('contact_person_invalid_utf8');
    }

    $originalSnapshot = $snapshot;
    $existing = '';
    foreach (['customer', 'contact'] as $group) {
        $values = is_array($snapshot[$group] ?? null) ? $snapshot[$group] : [];
        $candidate = microchipsCrmIntakeText($values['name'] ?? '');
        if ($candidate !== '') {
            $existing = $candidate;
            break;
        }
    }
    if ($existing === '') {
        $existing = microchipsCrmIntakeText($snapshot['name'] ?? '');
    }
    $normalisedSelected = trim($selected);
    $provenance = [
        'source' => 'POST[ONE_CLICK_BUY][CONTACT_PERSON]',
        'script' => MICROCHIPS_CRM_INTAKE_NATIVE_QUICKBUY_SCRIPT,
        'value' => $selected,
    ];
    if ($existing !== '') {
        if (trim($existing) !== $normalisedSelected) {
            return $review('contact_person_conflict');
        }
        $snapshot['_quickbuy_capture'] = [
            'original_snapshot' => $originalSnapshot, 'contact_person' => $provenance,
        ];
        return ['state' => 'unchanged', 'snapshot' => $snapshot];
    }

    $contact = is_array($snapshot['contact'] ?? null) ? $snapshot['contact'] : [];
    $contact['name'] = $selected;
    $snapshot['contact'] = $contact;
    $snapshot['_quickbuy_capture'] = [
        'original_snapshot' => $originalSnapshot, 'contact_person' => $provenance,
    ];
    return ['state' => 'enriched', 'snapshot' => $snapshot];
}

/** @param array<string, mixed> $context */
function microchipsCrmIntakeNativeQuickBuyReview(
    array $context,
    ?array $snapshot,
    string $reason,
    array $options = [],
    ?string $snapshotErrorClass = null
): array {
    $raw = [
        'source_type' => 'bitrix_sale_order',
        'event_parameters' => ['IS_NEW' => true],
        'order_id' => $context['order_id'] ?? null,
        'snapshot' => $snapshot,
        'quickbuy_context' => microchipsCrmIntakeNativeQuickBuyReviewContext($context),
    ];
    if ($snapshotErrorClass !== null) {
        $raw['snapshot_error_class'] = $snapshotErrorClass;
    }
    return microchipsCrmIntakeStoreReview($reason, $raw, $options);
}

function microchipsCrmIntakeNativeForm(int|string $formId, int|string $resultId): void
{
    try {
        microchipsCrmIntakeOnAfterResultAdd($formId, $resultId);
    } catch (Throwable $error) {
        // Source result remains in Bitrix for reconciliation. Never log payload
        // or exception text, which can contain contact data or credentials.
        error_log('CRM_INTAKE_CAPTURE_FAILED form=' . (int) $formId . ' result=' . (int) $resultId);
    }
}

function microchipsCrmIntakeNativeOrder(\Bitrix\Main\Event $event, array $options = []): void
{
    $order = $event->getParameter('ENTITY');
    try {
        $eventParameters = [
            'IS_NEW' => $event->getParameter('IS_NEW'), 'ENTITY' => $order,
        ];
        $isNew = $eventParameters['IS_NEW'] === true
            || $eventParameters['IS_NEW'] === 1
            || $eventParameters['IS_NEW'] === '1'
            || strtoupper((string) $eventParameters['IS_NEW']) === 'Y';
        $producerOptions = $options;
        $producerOptions['snapshotter'] = 'microchipsCrmIntakeNativeOrderSnapshot';
        if (!$isNew || !is_object($order)) {
            microchipsCrmIntakeOnSaleOrderSaved($eventParameters, $producerOptions);
            return;
        }

        $postIsArray = isset($_POST) && is_array($_POST);
        $oneClickBuy = $postIsArray ? ($_POST['ONE_CLICK_BUY'] ?? null) : null;
        $contactPersonPresent = is_array($oneClickBuy) && array_key_exists('CONTACT_PERSON', $oneClickBuy);
        $contactPerson = $contactPersonPresent ? $oneClickBuy['CONTACT_PERSON'] : null;
        $oneClickBuyIsArray = is_array($oneClickBuy);
        unset($oneClickBuy);
        $requestContext = microchipsCrmIntakeNativeQuickBuyRequestContext(
            isset($_SERVER['REQUEST_METHOD']) ? $_SERVER['REQUEST_METHOD'] : null,
            isset($_SERVER['SCRIPT_FILENAME']) ? $_SERVER['SCRIPT_FILENAME'] : null,
            $postIsArray ? ($_POST['SITE_ID'] ?? null) : null,
            $postIsArray ? ($_POST['PERSON_TYPE_ID'] ?? null) : null,
            $oneClickBuyIsArray,
            $contactPersonPresent,
            $contactPerson
        );
        if (!($requestContext['active'] ?? false)) {
            microchipsCrmIntakeOnSaleOrderSaved($eventParameters, $producerOptions);
            return;
        }
        if (!($requestContext['has_value'] ?? false) && !($requestContext['review_required'] ?? false)) {
            microchipsCrmIntakeOnSaleOrderSaved($eventParameters, $producerOptions);
            return;
        }
        $orderContext = microchipsCrmIntakeNativeQuickBuyOrderContext($order);
        if (!($orderContext['active'] ?? false)) {
            microchipsCrmIntakeOnSaleOrderSaved($eventParameters, $producerOptions);
            return;
        }
        $quickBuyContext = array_merge($requestContext, $orderContext);

        try {
            $snapshot = microchipsCrmIntakeNativeOrderSnapshot($order);
        } catch (Throwable $error) {
            microchipsCrmIntakeNativeQuickBuyReview(
                $quickBuyContext,
                null,
                'quickbuy_contact_capture_failed',
                $options,
                get_class($error)
            );
            return;
        }
        $enriched = microchipsCrmIntakeNativeEnrichQuickBuySnapshot($snapshot, $quickBuyContext);
        if (($enriched['state'] ?? '') === 'review') {
            microchipsCrmIntakeNativeQuickBuyReview(
                $quickBuyContext,
                $snapshot,
                'quickbuy_' . (string) ($enriched['reason'] ?? 'contact_person_invalid'),
                $options
            );
            return;
        }
        $enrichedSnapshot = $enriched['snapshot'] ?? $snapshot;
        $producerOptions['snapshotter'] = static fn (object $ignored): array => $enrichedSnapshot;
        microchipsCrmIntakeOnSaleOrderSaved($eventParameters, $producerOptions);
    } catch (Throwable $error) {
        $id = is_object($order) && method_exists($order, 'getId') ? (int) $order->getId() : 0;
        error_log('CRM_INTAKE_CAPTURE_FAILED order=' . $id);
    }
}

function microchipsCrmIntakeRegisterNativeHooks(): void
{
    static $registered = false;
    if ($registered) {
        return;
    }
    AddEventHandler('form', 'onAfterResultAdd', 'microchipsCrmIntakeNativeForm');
    \Bitrix\Main\EventManager::getInstance()->addEventHandler('sale', 'OnSaleOrderSaved', 'microchipsCrmIntakeNativeOrder');
    $registered = true;
}
