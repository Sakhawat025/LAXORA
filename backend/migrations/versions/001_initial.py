"""Initial LAXORA schema (frozen snapshot)."""
from alembic import op
import sqlalchemy as sa
revision = '001'
down_revision = None
branch_labels = None
depends_on = None
def upgrade():
# Frozen initial schema. Add new revision files for subsequent changes.
    op.create_table('practice_areas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('phone', sa.String(length=40), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('deleted', sa.Boolean(), nullable=False),
    sa.Column('token_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_role'), 'users', ['role'], unique=False)
    op.create_table('activities',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('lawyers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('area_id', sa.Integer(), nullable=True),
    sa.Column('biography', sa.Text(), nullable=False),
    sa.Column('education', sa.Text(), nullable=False),
    sa.Column('experience', sa.Integer(), nullable=False),
    sa.Column('jurisdiction', sa.String(length=120), nullable=False),
    sa.Column('location', sa.String(length=120), nullable=False),
    sa.Column('photo', sa.String(length=500), nullable=False),
    sa.Column('verification', sa.String(length=16), nullable=False),
    sa.Column('verification_note', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['area_id'], ['practice_areas.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )
    op.create_index(op.f('ix_lawyers_area_id'), 'lawyers', ['area_id'], unique=False)
    op.create_index(op.f('ix_lawyers_jurisdiction'), 'lawyers', ['jurisdiction'], unique=False)
    op.create_index(op.f('ix_lawyers_location'), 'lawyers', ['location'], unique=False)
    op.create_index(op.f('ix_lawyers_verification'), 'lawyers', ['verification'], unique=False)
    op.create_table('notifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('read', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notifications_user_id'), 'notifications', ['user_id'], unique=False)
    op.create_table('credentials',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('lawyer_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('filename', sa.String(length=200), nullable=False),
    sa.Column('stored_name', sa.String(length=64), nullable=False),
    sa.Column('mime', sa.String(length=80), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['lawyer_id'], ['lawyers.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_credentials_lawyer_id'), 'credentials', ['lawyer_id'], unique=False)
    op.create_table('slots',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('lawyer_id', sa.Integer(), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['lawyer_id'], ['lawyers.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_slots_lawyer_id'), 'slots', ['lawyer_id'], unique=False)
    op.create_index(op.f('ix_slots_starts_at'), 'slots', ['starts_at'], unique=False)
    op.create_index('unique_lawyer_slot', 'slots', ['lawyer_id', 'starts_at'], unique=True)
    op.create_table('appointments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('client_id', sa.Integer(), nullable=False),
    sa.Column('lawyer_id', sa.Integer(), nullable=False),
    sa.Column('slot_id', sa.Integer(), nullable=False),
    sa.Column('issue', sa.Text(), nullable=False),
    sa.Column('contact', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['lawyer_id'], ['lawyers.id'], ),
    sa.ForeignKeyConstraint(['slot_id'], ['slots.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_appointments_client_id'), 'appointments', ['client_id'], unique=False)
    op.create_index(op.f('ix_appointments_lawyer_id'), 'appointments', ['lawyer_id'], unique=False)
    op.create_index(op.f('ix_appointments_status'), 'appointments', ['status'], unique=False)
    op.create_index('one_active_booking_per_slot', 'appointments', ['slot_id'], unique=True, postgresql_where=sa.text("status IN ('pending','approved')"), sqlite_where=sa.text("status IN ('pending','approved')"))
    op.create_table('messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('appointment_id', sa.Integer(), nullable=False),
    sa.Column('sender_id', sa.Integer(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ),
    sa.ForeignKeyConstraint(['sender_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_messages_appointment_id'), 'messages', ['appointment_id'], unique=False)

def downgrade():
    for table in ['messages','notifications','credentials','appointments','activities','slots','lawyers','practice_areas','users']:
        op.drop_table(table)
