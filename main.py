"""
Konan — Asistente académico de Telegram
Todo en un solo archivo para simplificar el despliegue.
"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, time

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ==================== CONFIG ====================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "konan.db")

if not BOT_TOKEN:
    raise RuntimeError("Falta BOT_TOKEN. Crea un archivo .env con BOT_TOKEN=tu_token_de_botfather")


# ==================== BASE DE DATOS ====================
@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS materias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                nombre TEXT NOT NULL,
                creado_en TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tareas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                materia_id INTEGER NOT NULL REFERENCES materias(id) ON DELETE CASCADE,
                descripcion TEXT NOT NULL,
                fecha_limite TEXT NOT NULL,
                completada INTEGER NOT NULL DEFAULT 0,
                creado_en TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS examenes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                materia_id INTEGER NOT NULL REFERENCES materias(id) ON DELETE CASCADE,
                tema TEXT NOT NULL,
                fecha TEXT NOT NULL,
                creado_en TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS calificaciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                materia_id INTEGER NOT NULL REFERENCES materias(id) ON DELETE CASCADE,
                concepto TEXT NOT NULL,
                nota REAL NOT NULL,
                creado_en TEXT NOT NULL
            );
            """
        )


def now():
    return datetime.now().isoformat(timespec="seconds")


def add_materia(user_id, nombre):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO materias (user_id, nombre, creado_en) VALUES (?, ?, ?)",
            (user_id, nombre, now()),
        )
        return cur.lastrowid


def list_materias(user_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM materias WHERE user_id = ? ORDER BY nombre", (user_id,)
        ).fetchall()


def get_materia_by_nombre(user_id, nombre):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM materias WHERE user_id = ? AND nombre = ?", (user_id, nombre)
        ).fetchone()


def add_tarea(user_id, materia_id, descripcion, fecha_limite):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO tareas (user_id, materia_id, descripcion, fecha_limite, creado_en)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, materia_id, descripcion, fecha_limite, now()),
        )
        return cur.lastrowid


def list_tareas_pendientes(user_id):
    with get_conn() as conn:
        return conn.execute(
            """SELECT t.*, m.nombre AS materia_nombre
               FROM tareas t JOIN materias m ON m.id = t.materia_id
               WHERE t.user_id = ? AND t.completada = 0
               ORDER BY t.fecha_limite""",
            (user_id,),
        ).fetchall()


def add_examen(user_id, materia_id, tema, fecha):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO examenes (user_id, materia_id, tema, fecha, creado_en)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, materia_id, tema, fecha, now()),
        )
        return cur.lastrowid


def list_examenes(user_id):
    with get_conn() as conn:
        return conn.execute(
            """SELECT e.*, m.nombre AS materia_nombre
               FROM examenes e JOIN materias m ON m.id = e.materia_id
               WHERE e.user_id = ?
               ORDER BY e.fecha""",
            (user_id,),
        ).fetchall()


def add_calificacion(user_id, materia_id, concepto, nota):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO calificaciones (user_id, materia_id, concepto, nota, creado_en)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, materia_id, concepto, nota, now()),
        )
        return cur.lastrowid


def list_calificaciones(user_id, materia_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM calificaciones WHERE user_id = ? AND materia_id = ? ORDER BY creado_en",
            (user_id, materia_id),
        ).fetchall()


def promedio_materia(user_id, materia_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT AVG(nota) AS promedio FROM calificaciones WHERE user_id = ? AND materia_id = ?",
            (user_id, materia_id),
        ).fetchone()
        return row["promedio"]


def tareas_por_vencer(dias=2):
    with get_conn() as conn:
        return conn.execute(
            """SELECT t.*, m.nombre AS materia_nombre
               FROM tareas t JOIN materias m ON m.id = t.materia_id
               WHERE t.completada = 0
                 AND date(t.fecha_limite) <= date('now', ?)
                 AND date(t.fecha_limite) >= date('now')""",
            (f"+{dias} days",),
        ).fetchall()


def examenes_por_vencer(dias=2):
    with get_conn() as conn:
        return conn.execute(
            """SELECT e.*, m.nombre AS materia_nombre
               FROM examenes e JOIN materias m ON m.id = e.materia_id
               WHERE date(e.fecha) <= date('now', ?)
                 AND date(e.fecha) >= date('now')""",
            (f"+{dias} days",),
        ).fetchall()


# ==================== HANDLERS ====================
(
    TAREA_MATERIA, TAREA_DESC, TAREA_FECHA,
    EXAMEN_MATERIA, EXAMEN_TEMA, EXAMEN_FECHA,
    NOTA_MATERIA, NOTA_CONCEPTO, NOTA_VALOR,
) = range(9)


def _fecha_valida(texto):
    try:
        datetime.strptime(texto, "%Y-%m-%d")
        return True
    except ValueError:
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "¡Qué lo qué! Soy Konan, tu asistente académico.\n\n"
        "Comandos disponibles:\n"
        "/materia_add <nombre> — agregar materia\n"
        "/materias — ver tus materias\n"
        "/tarea_add — agregar tarea (flujo guiado)\n"
        "/tareas — ver tareas pendientes\n"
        "/examen_add — agregar examen (flujo guiado)\n"
        "/examenes — ver tus exámenes\n"
        "/nota_add — registrar calificación (flujo guiado)\n"
        "/notas <materia> — ver calificaciones de una materia\n"
        "/cancel — cancelar el flujo actual"
    )


async def materia_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /materia_add <nombre de la materia>")
        return
    nombre = " ".join(context.args)
    user_id = update.effective_user.id
    if get_materia_by_nombre(user_id, nombre):
        await update.message.reply_text(f"Ya tienes registrada la materia «{nombre}».")
        return
    add_materia(user_id, nombre)
    await update.message.reply_text(f"Materia «{nombre}» agregada ✅")


async def materias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    filas = list_materias(user_id)
    if not filas:
        await update.message.reply_text("No tienes materias registradas. Usa /materia_add <nombre>.")
        return
    texto = "\n".join(f"• {f['nombre']}" for f in filas)
    await update.message.reply_text(f"Tus materias:\n{texto}")


async def tarea_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    filas = list_materias(user_id)
    if not filas:
        await update.message.reply_text("Primero agrega una materia con /materia_add <nombre>.")
        return ConversationHandler.END
    nombres = ", ".join(f["nombre"] for f in filas)
    await update.message.reply_text(f"¿Para cuál materia? (opciones: {nombres})")
    return TAREA_MATERIA


async def tarea_add_materia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    materia = get_materia_by_nombre(user_id, update.message.text.strip())
    if not materia:
        await update.message.reply_text("No encontré esa materia. Escribe el nombre exacto o /cancel.")
        return TAREA_MATERIA
    context.user_data["materia_id"] = materia["id"]
    await update.message.reply_text("Describe la tarea:")
    return TAREA_DESC


async def tarea_add_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["descripcion"] = update.message.text.strip()
    await update.message.reply_text("Fecha límite (formato YYYY-MM-DD):")
    return TAREA_FECHA


async def tarea_add_fecha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if not _fecha_valida(texto):
        await update.message.reply_text("Formato inválido. Usa YYYY-MM-DD (ej: 2026-10-15).")
        return TAREA_FECHA
    user_id = update.effective_user.id
    add_tarea(user_id, context.user_data["materia_id"], context.user_data["descripcion"], texto)
    await update.message.reply_text("Tarea agregada ✅")
    context.user_data.clear()
    return ConversationHandler.END


async def tareas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    filas = list_tareas_pendientes(user_id)
    if not filas:
        await update.message.reply_text("No tienes tareas pendientes 🎉")
        return
    texto = "\n".join(
        f"#{f['id']} [{f['materia_nombre']}] {f['descripcion']} — vence {f['fecha_limite']}"
        for f in filas
    )
    await update.message.reply_text(f"Tareas pendientes:\n{texto}")


async def examen_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    filas = list_materias(user_id)
    if not filas:
        await update.message.reply_text("Primero agrega una materia con /materia_add <nombre>.")
        return ConversationHandler.END
    nombres = ", ".join(f["nombre"] for f in filas)
    await update.message.reply_text(f"¿Para cuál materia? (opciones: {nombres})")
    return EXAMEN_MATERIA


async def examen_add_materia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    materia = get_materia_by_nombre(user_id, update.message.text.strip())
    if not materia:
        await update.message.reply_text("No encontré esa materia. Escribe el nombre exacto o /cancel.")
        return EXAMEN_MATERIA
    context.user_data["materia_id"] = materia["id"]
    await update.message.reply_text("¿Tema o unidad del examen?")
    return EXAMEN_TEMA


async def examen_add_tema(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["tema"] = update.message.text.strip()
    await update.message.reply_text("Fecha del examen (YYYY-MM-DD):")
    return EXAMEN_FECHA


async def examen_add_fecha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if not _fecha_valida(texto):
        await update.message.reply_text("Formato inválido. Usa YYYY-MM-DD.")
        return EXAMEN_FECHA
    user_id = update.effective_user.id
    add_examen(user_id, context.user_data["materia_id"], context.user_data["tema"], texto)
    await update.message.reply_text("Examen agregado ✅")
    context.user_data.clear()
    return ConversationHandler.END


async def examenes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    filas = list_examenes(user_id)
    if not filas:
        await update.message.reply_text("No tienes exámenes registrados.")
        return
    texto = "\n".join(
        f"#{f['id']} [{f['materia_nombre']}] {f['tema']} — {f['fecha']}" for f in filas
    )
    await update.message.reply_text(f"Tus exámenes:\n{texto}")


async def nota_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    filas = list_materias(user_id)
    if not filas:
        await update.message.reply_text("Primero agrega una materia con /materia_add <nombre>.")
        return ConversationHandler.END
    nombres = ", ".join(f["nombre"] for f in filas)
    await update.message.reply_text(f"¿Para cuál materia? (opciones: {nombres})")
    return NOTA_MATERIA


async def nota_add_materia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    materia = get_materia_by_nombre(user_id, update.message.text.strip())
    if not materia:
        await update.message.reply_text("No encontré esa materia. Escribe el nombre exacto o /cancel.")
        return NOTA_MATERIA
    context.user_data["materia_id"] = materia["id"]
    await update.message.reply_text("¿Concepto de la nota? (ej: Parcial 1, Proyecto final)")
    return NOTA_CONCEPTO


async def nota_add_concepto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["concepto"] = update.message.text.strip()
    await update.message.reply_text("¿Cuál es la nota? (número)")
    return NOTA_VALOR


async def nota_add_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip().replace(",", ".")
    try:
        nota = float(texto)
    except ValueError:
        await update.message.reply_text("Eso no es un número válido. Intenta de nuevo.")
        return NOTA_VALOR
    user_id = update.effective_user.id
    add_calificacion(user_id, context.user_data["materia_id"], context.user_data["concepto"], nota)
    await update.message.reply_text("Calificación registrada ✅")
    context.user_data.clear()
    return ConversationHandler.END


async def notas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /notas <nombre de la materia>")
        return
    user_id = update.effective_user.id
    nombre = " ".join(context.args)
    materia = get_materia_by_nombre(user_id, nombre)
    if not materia:
        await update.message.reply_text("No encontré esa materia.")
        return
    filas = list_calificaciones(user_id, materia["id"])
    if not filas:
        await update.message.reply_text(f"No hay calificaciones registradas para «{nombre}».")
        return
    texto = "\n".join(f"{f['concepto']}: {f['nota']}" for f in filas)
    promedio = promedio_materia(user_id, materia["id"])
    await update.message.reply_text(f"{texto}\n\nPromedio: {promedio:.2f}")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Flujo cancelado.")
    return ConversationHandler.END


async def enviar_recordatorios(context: ContextTypes.DEFAULT_TYPE):
    tareas_prox = tareas_por_vencer(dias=2)
    examenes_prox = examenes_por_vencer(dias=2)

    por_usuario = {}
    for t in tareas_prox:
        por_usuario.setdefault(t["user_id"], []).append(
            f"📝 Tarea «{t['descripcion']}» ({t['materia_nombre']}) vence el {t['fecha_limite']}"
        )
    for e in examenes_prox:
        por_usuario.setdefault(e["user_id"], []).append(
            f"📚 Examen de {e['materia_nombre']} ({e['tema']}) el {e['fecha']}"
        )

    for user_id, mensajes in por_usuario.items():
        texto = "Recordatorio:\n" + "\n".join(mensajes)
        try:
            await context.bot.send_message(chat_id=user_id, text=texto)
        except Exception:
            pass


def registrar_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("materia_add", materia_add))
    app.add_handler(CommandHandler("materias", materias))
    app.add_handler(CommandHandler("tareas", tareas))
    app.add_handler(CommandHandler("examenes", examenes))
    app.add_handler(CommandHandler("notas", notas))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("tarea_add", tarea_add_start)],
        states={
            TAREA_MATERIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, tarea_add_materia)],
            TAREA_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, tarea_add_desc)],
            TAREA_FECHA: [MessageHandler(filters.TEXT & ~filters.COMMAND, tarea_add_fecha)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("examen_add", examen_add_start)],
        states={
            EXAMEN_MATERIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, examen_add_materia)],
            EXAMEN_TEMA: [MessageHandler(filters.TEXT & ~filters.COMMAND, examen_add_tema)],
            EXAMEN_FECHA: [MessageHandler(filters.TEXT & ~filters.COMMAND, examen_add_fecha)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("nota_add", nota_add_start)],
        states={
            NOTA_MATERIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, nota_add_materia)],
            NOTA_CONCEPTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, nota_add_concepto)],
            NOTA_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, nota_add_valor)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    app.job_queue.run_daily(enviar_recordatorios, time=time(hour=8, minute=0))


# ==================== MAIN ====================
def main():
    print("Iniciando Konan...")
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()
    registrar_handlers(app)

    print("Konan está corriendo. Ctrl+C para detener.")
    app.run_polling()


if __name__ == "__main__":
    main()
