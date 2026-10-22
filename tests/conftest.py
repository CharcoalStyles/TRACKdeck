import freezegun

# freezegun walks every loaded module's attributes when a test freezes time,
# which trips transformers' lazy submodule imports (a NameError from an
# optional vision dependency) once anything has imported it.
freezegun.configure(extend_ignore_list=["transformers"])
