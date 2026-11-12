"""
Example tenant app. The views contain no tenant filtering: the router sends
every Note query to the database of the organization selected by
TenantMiddleware.
"""

from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from organizations.decorators import tenant_required

from .models import Note


class NoteForm(forms.ModelForm):
    class Meta:
        model = Note
        fields = ["title", "body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 3})}


@tenant_required
def note_list(request):
    limit = request.organization.item_limit()
    count = Note.objects.count()
    context = {
        "notes": Note.objects.all(),
        "form": NoteForm(),
        "limit": limit,
        "limit_reached": bool(limit) and count >= limit,
    }
    return render(request, "notes/list.html", context)


@require_POST
@tenant_required
def note_create(request):
    limit = request.organization.item_limit()
    if limit and Note.objects.count() >= limit:
        messages.error(request, "Your plan's limit is reached.")
        return redirect("dashboard")

    form = NoteForm(request.POST)
    if form.is_valid():
        note = form.save(commit=False)
        note.author_id = request.user.id
        note.author_name = str(request.user)
        note.save()
    else:
        messages.error(request, "A note needs a title.")
    return redirect("dashboard")


@require_POST
@tenant_required
def note_delete(request, note_id):
    get_object_or_404(Note, id=note_id).delete()
    return redirect("dashboard")
