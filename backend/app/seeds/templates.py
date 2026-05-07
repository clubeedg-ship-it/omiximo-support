"""Seed script: initial response templates.

Inserts global (marketplace_account_id=None) Jinja2 templates for every
supported category × language combination. The function is idempotent: it
checks for an existing row with the same (category, language,
marketplace_account_id IS NULL) key and skips insertion if one is found.

Available Jinja2 slots in every template body:
    {{ order_id }}          – Mirakl order identifier
    {{ tracking_number }}   – Carrier tracking number
    {{ delivery_date }}     – Estimated or actual delivery date
    {{ customer_name }}     – Customer's name (optional, may be empty)
    {{ marketplace_name }}  – Human-readable marketplace name

Design constraints (see CLAUDE.md D1 and D3):
- Templates NEVER promise refunds.
- Templates NEVER approve returns or warranty claims.
- Templates NEVER direct customers outside the marketplace message channel.
- Defect / complaint templates acknowledge the issue and escalate only.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.response_template import ResponseTemplate

# ---------------------------------------------------------------------------
# Template definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _TemplateSpec:
    category: str
    language: str
    template_body: str


# ---------------------------------------------------------------------------
# tracking_update
# ---------------------------------------------------------------------------
_TRACKING_UPDATE_EN = """\
Dear {% if customer_name %}{{ customer_name }}{% else %}customer{% endif %},

Thank you for your inquiry about order {{ order_id }}.

Your package is currently on its way. You can track your shipment using \
tracking number {{ tracking_number }}.

If you have any further questions, please do not hesitate to contact us \
through this channel.

Kind regards,
{{ marketplace_name }} Customer Service"""

_TRACKING_UPDATE_NL = """\
Beste {% if customer_name %}{{ customer_name }}{% else %}klant{% endif %},

Bedankt voor uw vraag over bestelling {{ order_id }}.

Uw pakket is momenteel onderweg. U kunt uw zending volgen met \
trackingnummer {{ tracking_number }}.

Heeft u nog verdere vragen, aarzel dan niet om contact met ons op te nemen \
via dit kanaal.

Met vriendelijke groet,
{{ marketplace_name }} Klantenservice"""

_TRACKING_UPDATE_FR = """\
Cher(e) {% if customer_name %}{{ customer_name }}{% else %}client(e){% endif %},

Merci pour votre demande concernant la commande {{ order_id }}.

Votre colis est actuellement en cours d'acheminement. Vous pouvez suivre \
votre envoi grâce au numéro de suivi {{ tracking_number }}.

Si vous avez d'autres questions, n'hésitez pas à nous contacter via ce canal.

Cordialement,
Service client {{ marketplace_name }}"""

_TRACKING_UPDATE_DE = """\
Sehr geehrte(r) {% if customer_name %}{{ customer_name }}{% else %}Kunde/Kundin{% endif %},

vielen Dank für Ihre Anfrage zur Bestellung {{ order_id }}.

Ihr Paket ist derzeit unterwegs. Sie können Ihre Sendung mit der \
Sendungsverfolgungsnummer {{ tracking_number }} verfolgen.

Sollten Sie weitere Fragen haben, stehen wir Ihnen gerne über diesen Kanal \
zur Verfügung.

Mit freundlichen Grüßen,
{{ marketplace_name }} Kundenservice"""

# ---------------------------------------------------------------------------
# invoice_request
# ---------------------------------------------------------------------------
_INVOICE_REQUEST_EN = """\
Dear {% if customer_name %}{{ customer_name }}{% else %}customer{% endif %},

Thank you for your message regarding order {{ order_id }}.

We have registered your request for an invoice. Our team is processing your \
request and will provide the relevant document as soon as possible through \
this channel.

If you need any additional assistance, please reply to this message.

Kind regards,
{{ marketplace_name }} Customer Service"""

_INVOICE_REQUEST_NL = """\
Beste {% if customer_name %}{{ customer_name }}{% else %}klant{% endif %},

Bedankt voor uw bericht over bestelling {{ order_id }}.

Wij hebben uw aanvraag voor een factuur ontvangen. Ons team verwerkt uw \
aanvraag en zal het betreffende document zo spoedig mogelijk via dit kanaal \
bezorgen.

Heeft u verdere vragen, antwoord dan op dit bericht.

Met vriendelijke groet,
{{ marketplace_name }} Klantenservice"""

_INVOICE_REQUEST_FR = """\
Cher(e) {% if customer_name %}{{ customer_name }}{% else %}client(e){% endif %},

Merci pour votre message concernant la commande {{ order_id }}.

Nous avons bien enregistré votre demande de facture. Notre équipe traite \
votre demande et vous fera parvenir le document concerné dans les meilleurs \
délais via ce canal.

Pour toute question complémentaire, n'hésitez pas à répondre à ce message.

Cordialement,
Service client {{ marketplace_name }}"""

_INVOICE_REQUEST_DE = """\
Sehr geehrte(r) {% if customer_name %}{{ customer_name }}{% else %}Kunde/Kundin{% endif %},

vielen Dank für Ihre Nachricht zur Bestellung {{ order_id }}.

Wir haben Ihre Anfrage für eine Rechnung erhalten. Unser Team bearbeitet Ihre \
Anfrage und wird Ihnen das entsprechende Dokument so bald wie möglich über \
diesen Kanal zukommen lassen.

Bei weiteren Fragen antworten Sie bitte auf diese Nachricht.

Mit freundlichen Grüßen,
{{ marketplace_name }} Kundenservice"""

# ---------------------------------------------------------------------------
# return_inquiry
# ---------------------------------------------------------------------------
_RETURN_INQUIRY_EN = """\
Dear {% if customer_name %}{{ customer_name }}{% else %}customer{% endif %},

Thank you for your message about order {{ order_id }}.

We have received your inquiry regarding a return. We are reviewing your \
request and will come back to you with further information through this \
channel as quickly as possible.

Please do not send the item back until you have received further instructions \
from us.

Kind regards,
{{ marketplace_name }} Customer Service"""

_RETURN_INQUIRY_NL = """\
Beste {% if customer_name %}{{ customer_name }}{% else %}klant{% endif %},

Bedankt voor uw bericht over bestelling {{ order_id }}.

Wij hebben uw vraag over een retourzending ontvangen. Wij beoordelen uw \
verzoek en nemen zo spoedig mogelijk via dit kanaal contact met u op met \
verdere informatie.

Stuur het artikel nog niet terug totdat u verdere instructies van ons heeft \
ontvangen.

Met vriendelijke groet,
{{ marketplace_name }} Klantenservice"""

_RETURN_INQUIRY_FR = """\
Cher(e) {% if customer_name %}{{ customer_name }}{% else %}client(e){% endif %},

Merci pour votre message concernant la commande {{ order_id }}.

Nous avons bien reçu votre demande de retour. Nous examinons votre demande et \
vous recontacterons via ce canal dans les meilleurs délais avec des \
informations complémentaires.

Veuillez ne pas renvoyer l'article avant d'avoir reçu nos instructions.

Cordialement,
Service client {{ marketplace_name }}"""

_RETURN_INQUIRY_DE = """\
Sehr geehrte(r) {% if customer_name %}{{ customer_name }}{% else %}Kunde/Kundin{% endif %},

vielen Dank für Ihre Nachricht zur Bestellung {{ order_id }}.

Wir haben Ihre Anfrage bezüglich einer Rücksendung erhalten. Wir prüfen Ihre \
Anfrage und werden uns so schnell wie möglich über diesen Kanal mit weiteren \
Informationen bei Ihnen melden.

Bitte senden Sie den Artikel erst zurück, nachdem Sie weitere Anweisungen von \
uns erhalten haben.

Mit freundlichen Grüßen,
{{ marketplace_name }} Kundenservice"""

# ---------------------------------------------------------------------------
# complaint
# ---------------------------------------------------------------------------
_COMPLAINT_EN = """\
Dear {% if customer_name %}{{ customer_name }}{% else %}customer{% endif %},

Thank you for taking the time to contact us about order {{ order_id }}.

We are sorry to hear that your experience did not meet your expectations. \
We take every complaint seriously and have escalated your case to our \
customer care team for thorough review.

A member of our team will follow up with you through this channel as soon \
as possible.

Kind regards,
{{ marketplace_name }} Customer Service"""

_COMPLAINT_NL = """\
Beste {% if customer_name %}{{ customer_name }}{% else %}klant{% endif %},

Bedankt dat u de tijd heeft genomen om contact met ons op te nemen over \
bestelling {{ order_id }}.

Het spijt ons te horen dat uw ervaring niet aan uw verwachtingen heeft \
voldaan. Wij nemen elke klacht serieus en hebben uw zaak doorgestuurd naar \
ons klantenzorgteam voor een grondige beoordeling.

Een medewerker van ons team neemt zo spoedig mogelijk via dit kanaal contact \
met u op.

Met vriendelijke groet,
{{ marketplace_name }} Klantenservice"""

_COMPLAINT_FR = """\
Cher(e) {% if customer_name %}{{ customer_name }}{% else %}client(e){% endif %},

Merci de nous avoir contactés au sujet de la commande {{ order_id }}.

Nous sommes désolés d'apprendre que votre expérience n'a pas été à la hauteur \
de vos attentes. Nous prenons chaque réclamation au sérieux et avons transmis \
votre dossier à notre équipe du service client pour un examen approfondi.

Un membre de notre équipe vous recontactera via ce canal dans les meilleurs \
délais.

Cordialement,
Service client {{ marketplace_name }}"""

_COMPLAINT_DE = """\
Sehr geehrte(r) {% if customer_name %}{{ customer_name }}{% else %}Kunde/Kundin{% endif %},

vielen Dank, dass Sie sich bezüglich Ihrer Bestellung {{ order_id }} an uns \
gewandt haben.

Es tut uns leid zu hören, dass Ihre Erfahrung nicht Ihren Erwartungen \
entsprochen hat. Wir nehmen jede Beschwerde ernst und haben Ihren Fall zur \
eingehenden Prüfung an unser Kundendienst-Team weitergeleitet.

Ein Mitglied unseres Teams wird sich so bald wie möglich über diesen Kanal \
bei Ihnen melden.

Mit freundlichen Grüßen,
{{ marketplace_name }} Kundenservice"""

# ---------------------------------------------------------------------------
# defect_report
# ---------------------------------------------------------------------------
_DEFECT_REPORT_EN = """\
Dear {% if customer_name %}{{ customer_name }}{% else %}customer{% endif %},

Thank you for contacting us about order {{ order_id }}.

We are sorry to hear that you have encountered an issue with your product. \
We have noted your report and have escalated it to our specialist team for \
assessment.

We will get back to you through this channel with further information as \
soon as our team has reviewed the details.

Kind regards,
{{ marketplace_name }} Customer Service"""

_DEFECT_REPORT_NL = """\
Beste {% if customer_name %}{{ customer_name }}{% else %}klant{% endif %},

Bedankt voor uw bericht over bestelling {{ order_id }}.

Het spijt ons te horen dat u een probleem heeft ondervonden met uw product. \
Wij hebben uw melding geregistreerd en doorgestuurd naar ons specialistenteam \
voor beoordeling.

Wij nemen zo spoedig mogelijk via dit kanaal contact met u op met verdere \
informatie zodra ons team de details heeft beoordeeld.

Met vriendelijke groet,
{{ marketplace_name }} Klantenservice"""

_DEFECT_REPORT_FR = """\
Cher(e) {% if customer_name %}{{ customer_name }}{% else %}client(e){% endif %},

Merci de nous avoir contactés au sujet de la commande {{ order_id }}.

Nous sommes désolés d'apprendre que vous avez rencontré un problème avec \
votre produit. Nous avons enregistré votre signalement et l'avons transmis \
à notre équipe spécialisée pour évaluation.

Nous vous recontacterons via ce canal avec des informations supplémentaires \
dès que notre équipe aura examiné les détails.

Cordialement,
Service client {{ marketplace_name }}"""

_DEFECT_REPORT_DE = """\
Sehr geehrte(r) {% if customer_name %}{{ customer_name }}{% else %}Kunde/Kundin{% endif %},

vielen Dank, dass Sie sich bezüglich Ihrer Bestellung {{ order_id }} an uns \
gewandt haben.

Es tut uns leid zu hören, dass Sie ein Problem mit Ihrem Produkt festgestellt \
haben. Wir haben Ihre Meldung erfasst und zur Bewertung an unser \
Spezialistenteam weitergeleitet.

Wir melden uns so bald wie möglich über diesen Kanal bei Ihnen, sobald unser \
Team die Details geprüft hat.

Mit freundlichen Grüßen,
{{ marketplace_name }} Kundenservice"""

# ---------------------------------------------------------------------------
# general_inquiry
# ---------------------------------------------------------------------------
_GENERAL_INQUIRY_EN = """\
Dear {% if customer_name %}{{ customer_name }}{% else %}customer{% endif %},

Thank you for your message about order {{ order_id }}.

We have received your inquiry and are looking into it. We will respond to \
you through this channel as soon as possible.

If you have any additional details you would like to share, please reply to \
this message.

Kind regards,
{{ marketplace_name }} Customer Service"""

_GENERAL_INQUIRY_NL = """\
Beste {% if customer_name %}{{ customer_name }}{% else %}klant{% endif %},

Bedankt voor uw bericht over bestelling {{ order_id }}.

Wij hebben uw vraag ontvangen en onderzoeken deze. Wij reageren zo spoedig \
mogelijk via dit kanaal.

Indien u aanvullende details wilt delen, kunt u op dit bericht antwoorden.

Met vriendelijke groet,
{{ marketplace_name }} Klantenservice"""

_GENERAL_INQUIRY_FR = """\
Cher(e) {% if customer_name %}{{ customer_name }}{% else %}client(e){% endif %},

Merci pour votre message concernant la commande {{ order_id }}.

Nous avons bien reçu votre demande et l'examinons actuellement. Nous vous \
répondrons via ce canal dans les meilleurs délais.

Si vous souhaitez partager des informations supplémentaires, n'hésitez pas \
à répondre à ce message.

Cordialement,
Service client {{ marketplace_name }}"""

_GENERAL_INQUIRY_DE = """\
Sehr geehrte(r) {% if customer_name %}{{ customer_name }}{% else %}Kunde/Kundin{% endif %},

vielen Dank für Ihre Nachricht zur Bestellung {{ order_id }}.

Wir haben Ihre Anfrage erhalten und bearbeiten diese. Wir werden Ihnen so \
bald wie möglich über diesen Kanal antworten.

Falls Sie weitere Details mitteilen möchten, antworten Sie bitte auf diese \
Nachricht.

Mit freundlichen Grüßen,
{{ marketplace_name }} Kundenservice"""

# ---------------------------------------------------------------------------
# delivery_confirmation
# ---------------------------------------------------------------------------
_DELIVERY_CONFIRMATION_EN = """\
Dear {% if customer_name %}{{ customer_name }}{% else %}customer{% endif %},

Thank you for your message about order {{ order_id }}.

According to the information available to us, your order was delivered \
on {{ delivery_date }}. If you believe there has been an error, please reply \
to this message with further details so we can investigate.

Kind regards,
{{ marketplace_name }} Customer Service"""

_DELIVERY_CONFIRMATION_NL = """\
Beste {% if customer_name %}{{ customer_name }}{% else %}klant{% endif %},

Bedankt voor uw bericht over bestelling {{ order_id }}.

Volgens de informatie waarover wij beschikken is uw bestelling op \
{{ delivery_date }} afgeleverd. Als u denkt dat er een fout is opgetreden, \
antwoord dan op dit bericht met verdere details zodat wij dit kunnen \
onderzoeken.

Met vriendelijke groet,
{{ marketplace_name }} Klantenservice"""

_DELIVERY_CONFIRMATION_FR = """\
Cher(e) {% if customer_name %}{{ customer_name }}{% else %}client(e){% endif %},

Merci pour votre message concernant la commande {{ order_id }}.

Selon les informations dont nous disposons, votre commande a été livrée \
le {{ delivery_date }}. Si vous pensez qu'une erreur s'est produite, veuillez \
répondre à ce message avec plus de détails afin que nous puissions enquêter.

Cordialement,
Service client {{ marketplace_name }}"""

_DELIVERY_CONFIRMATION_DE = """\
Sehr geehrte(r) {% if customer_name %}{{ customer_name }}{% else %}Kunde/Kundin{% endif %},

vielen Dank für Ihre Nachricht zur Bestellung {{ order_id }}.

Unseren Informationen zufolge wurde Ihre Bestellung am {{ delivery_date }} \
zugestellt. Falls Sie der Meinung sind, dass ein Fehler vorliegt, antworten \
Sie bitte auf diese Nachricht mit weiteren Details, damit wir dies \
untersuchen können.

Mit freundlichen Grüßen,
{{ marketplace_name }} Kundenservice"""

# ---------------------------------------------------------------------------
# Master template registry
# ---------------------------------------------------------------------------
TEMPLATE_SPECS: Sequence[_TemplateSpec] = [
    # tracking_update
    _TemplateSpec("tracking_update", "en", _TRACKING_UPDATE_EN),
    _TemplateSpec("tracking_update", "nl", _TRACKING_UPDATE_NL),
    _TemplateSpec("tracking_update", "fr", _TRACKING_UPDATE_FR),
    _TemplateSpec("tracking_update", "de", _TRACKING_UPDATE_DE),
    # invoice_request
    _TemplateSpec("invoice_request", "en", _INVOICE_REQUEST_EN),
    _TemplateSpec("invoice_request", "nl", _INVOICE_REQUEST_NL),
    _TemplateSpec("invoice_request", "fr", _INVOICE_REQUEST_FR),
    _TemplateSpec("invoice_request", "de", _INVOICE_REQUEST_DE),
    # return_inquiry
    _TemplateSpec("return_inquiry", "en", _RETURN_INQUIRY_EN),
    _TemplateSpec("return_inquiry", "nl", _RETURN_INQUIRY_NL),
    _TemplateSpec("return_inquiry", "fr", _RETURN_INQUIRY_FR),
    _TemplateSpec("return_inquiry", "de", _RETURN_INQUIRY_DE),
    # complaint
    _TemplateSpec("complaint", "en", _COMPLAINT_EN),
    _TemplateSpec("complaint", "nl", _COMPLAINT_NL),
    _TemplateSpec("complaint", "fr", _COMPLAINT_FR),
    _TemplateSpec("complaint", "de", _COMPLAINT_DE),
    # defect_report
    _TemplateSpec("defect_report", "en", _DEFECT_REPORT_EN),
    _TemplateSpec("defect_report", "nl", _DEFECT_REPORT_NL),
    _TemplateSpec("defect_report", "fr", _DEFECT_REPORT_FR),
    _TemplateSpec("defect_report", "de", _DEFECT_REPORT_DE),
    # general_inquiry
    _TemplateSpec("general_inquiry", "en", _GENERAL_INQUIRY_EN),
    _TemplateSpec("general_inquiry", "nl", _GENERAL_INQUIRY_NL),
    _TemplateSpec("general_inquiry", "fr", _GENERAL_INQUIRY_FR),
    _TemplateSpec("general_inquiry", "de", _GENERAL_INQUIRY_DE),
    # delivery_confirmation
    _TemplateSpec("delivery_confirmation", "en", _DELIVERY_CONFIRMATION_EN),
    _TemplateSpec("delivery_confirmation", "nl", _DELIVERY_CONFIRMATION_NL),
    _TemplateSpec("delivery_confirmation", "fr", _DELIVERY_CONFIRMATION_FR),
    _TemplateSpec("delivery_confirmation", "de", _DELIVERY_CONFIRMATION_DE),
]


# ---------------------------------------------------------------------------
# Seed function
# ---------------------------------------------------------------------------

async def seed_templates(db_session: AsyncSession) -> dict[str, Any]:
    """Insert global response templates if they do not already exist.

    Idempotent: rows with a matching (category, language) pair where
    marketplace_account_id IS NULL are skipped.

    Args:
        db_session: An open async SQLAlchemy session. The caller is
            responsible for committing (or rolling back) the transaction.

    Returns:
        A summary dict with keys ``inserted`` (int), ``skipped`` (int), and
        ``total`` (int).

    Example::

        async with AsyncSessionLocal() as session:
            summary = await seed_templates(session)
            await session.commit()
            print(summary)
    """
    inserted = 0
    skipped = 0

    for spec in TEMPLATE_SPECS:
        # Check whether a global template for this (category, language) exists.
        result = await db_session.execute(
            select(ResponseTemplate).where(
                ResponseTemplate.category == spec.category,
                ResponseTemplate.language == spec.language,
                ResponseTemplate.marketplace_account_id.is_(None),
            )
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            skipped += 1
            continue

        db_session.add(
            ResponseTemplate(
                id=uuid.uuid4(),
                marketplace_account_id=None,
                category=spec.category,
                language=spec.language,
                template_body=spec.template_body,
                is_active=True,
            )
        )
        inserted += 1

    return {
        "inserted": inserted,
        "skipped": skipped,
        "total": len(TEMPLATE_SPECS),
    }
