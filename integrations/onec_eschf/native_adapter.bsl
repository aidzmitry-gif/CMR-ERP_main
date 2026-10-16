// Candidate common-module BODY only. Not installed, compiled or callable yet.
// Context/metadata flags, dependencies, native messages and byte conversion:
// unresolved; see dependencies.json and docs/eschf/g03-native-adapter.md.
// The caller must resolve a trusted ERP binding before reaching this method.
// Does not call upper formation, business writes, signing or sending.

Функция ПодготовитьИсходныйXMLЛокально(СсылкаНаОбъект) Экспорт

    Результат = Новый Структура;
    Результат.Вставить("status", "unsupported_scenario");
    Результат.Вставить("xml_text", Неопределено);
    Результат.Вставить("number", "");
    Результат.Вставить("native_error", "");
    Результат.Вставить("refusal", Ложь);
    Результат.Вставить("diagnostic_capture", "unresolved");
    Результат.Вставить("native_messages", Новый Массив);

    // Exact observed metadata symbols; no metadata packaging/context is assumed.
    Если ТипЗнч(СсылкаНаОбъект) <> Тип("ДокументСсылка.СчетФактураВыданный") Тогда
        Возврат Результат;
    КонецЕсли;
    Если СсылкаНаОбъект.ВидСчетаФактуры <>
            Перечисления.ВидСчетаФактурыВыставленного.НаРеализацию
        ИЛИ СсылкаНаОбъект.ТипСчетаФактуры <> Перечисления.ТипыЭСЧФ.Исходный
        ИЛИ СсылкаНаОбъект.КодТипаСчетаФактуры_Локализация <>
            Перечисления.КодыТиповСчетовФактур_Локализация.Исходный
        ИЛИ СсылкаНаОбъект.Итоговая Тогда
        Возврат Результат;
    КонецЕсли;

    ПространствоИмен = "http://www.w3schools.com";
    НомерЭСЧФ = "";
    ТекстОшибки = "";
    Отказ = Ложь;

    // inner-module.bsl:266-783; reference arguments carry the native number/error.
    ТекстXML = ЭлектронныеДокументыВнутренний_Локализация.ЗаполнитьДанныеПоСчетуФактуре(
        СсылкаНаОбъект, ПространствоИмен,
        СсылкаНаОбъект.КодТипаСчетаФактуры_Локализация,
        НомерЭСЧФ, ТекстОшибки, Отказ);

    Если Отказ ИЛИ ЗначениеЗаполнено(ТекстОшибки) Тогда
        Результат.status = "native_failure";
    ИначеЕсли ТипЗнч(ТекстXML) <> Тип("Строка") ИЛИ НЕ ЗначениеЗаполнено(ТекстXML) Тогда
        // manager:7285 + inner:271-272 can lose the validation reason here.
        // Do not fabricate native_error or call an unverified message-capture API.
        Результат.status = "native_empty_result";
    Иначе
        // Same cleanup and position as native upper formation: inner:818.
        ЭлектронныеДокументыВнутренний_Локализация.УдалитьПространствоИмен(
            ТекстXML, ПространствоИмен, ТекстОшибки, Отказ);
        Если Отказ ИЛИ ЗначениеЗаполнено(ТекстОшибки) Тогда
            Результат.status = "native_failure";
        Иначе
            Результат.status = "candidate";
            Результат.xml_text = ТекстXML;
        КонецЕсли;
    КонецЕсли;

    Результат.number = НомерЭСЧФ;
    Результат.native_error = ТекстОшибки;
    Результат.refusal = Отказ;
    Возврат Результат;

КонецФункции
