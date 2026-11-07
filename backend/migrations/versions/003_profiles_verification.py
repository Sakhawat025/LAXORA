"""Photo storage and explicit verification applications."""
from alembic import op
import sqlalchemy as sa
revision='003'
down_revision='002'
branch_labels=None
depends_on=None
def upgrade():
    op.add_column('users',sa.Column('avatar',sa.String(64),nullable=False,server_default=''))
    op.create_table('verification_applications',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False,unique=True),sa.Column('status',sa.String(20),nullable=False),sa.Column('details',sa.JSON(),nullable=False),sa.Column('note',sa.Text(),nullable=False),sa.Column('submitted_at',sa.DateTime(timezone=True)),sa.Column('reviewed_by',sa.Integer(),sa.ForeignKey('users.id')),sa.Column('reviewed_at',sa.DateTime(timezone=True)),sa.Column('version',sa.Integer(),nullable=False))
    op.create_index('ix_verification_applications_status','verification_applications',['status'])
    op.create_table('verification_documents',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),sa.Column('kind',sa.String(40),nullable=False),sa.Column('filename',sa.String(200),nullable=False),sa.Column('stored_name',sa.String(64),nullable=False),sa.Column('mime',sa.String(80),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_verification_documents_user_id','verification_documents',['user_id'])
def downgrade():
    op.drop_table('verification_documents');op.drop_table('verification_applications');op.drop_column('users','avatar')
