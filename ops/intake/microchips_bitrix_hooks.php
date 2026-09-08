<?php
declare(strict_types=1);

/** Native Bitrix bridge. Require after the producer, then explicitly register.
 * Vendor contracts verified on microchips.by 2026-09-07:
 * sale/lib/orderbase.php:1392, eventactions.php:17, entitypropertyvalue.php:799/972,
 * main/lib/eventmanager.php:103. No network or source mutation in these hooks.
 */
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

function microchipsCrmIntakeNativeOrder(\Bitrix\Main\Event $event): void
{
    $order = $event->getParameter('ENTITY');
    try {
        microchipsCrmIntakeOnSaleOrderSaved([
            'IS_NEW' => $event->getParameter('IS_NEW'), 'ENTITY' => $order,
        ], ['snapshotter' => 'microchipsCrmIntakeNativeOrderSnapshot']);
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
