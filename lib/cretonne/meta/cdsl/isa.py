"""Defining instruction set architectures."""
from __future__ import absolute_import
from .predicates import And
from .registers import RegClass, Register
from .ast import Apply

# The typing module is only required by mypy, and we don't use these imports
# outside type comments.
try:
    from typing import Tuple, Union, Any, Iterable, Sequence, List, Set, TYPE_CHECKING  # noqa
    if TYPE_CHECKING:
        from .instructions import MaybeBoundInst, InstructionGroup, InstructionFormat  # noqa
        from .predicates import PredNode  # noqa
        from .settings import SettingGroup  # noqa
        from .types import ValueType  # noqa
        from .registers import RegBank  # noqa
        OperandConstraint = Union[RegClass, Register, int]
        ConstraintSeq = Union[OperandConstraint, Tuple[OperandConstraint, ...]]
        # Instruction specification for encodings. Allows for predicated
        # instructions.
        InstSpec = Union[MaybeBoundInst, Apply]
        BranchRange = Sequence[int]
except ImportError:
    pass


class TargetISA(object):
    """
    A target instruction set architecture.

    The `TargetISA` class collects everything known about a target ISA.

    :param name: Short mnemonic name for the ISA.
    :param instruction_groups: List of `InstructionGroup` instances that are
        relevant for this ISA.
    """

    def __init__(self, name, instruction_groups):
        # type: (str, Sequence[InstructionGroup]) -> None
        self.name = name
        self.settings = None  # type: SettingGroup
        self.instruction_groups = instruction_groups
        self.cpumodes = list()  # type: List[CPUMode]
        self.regbanks = list()  # type: List[RegBank]

    def finish(self):
        # type: () -> TargetISA
        """
        Finish the definition of a target ISA after adding all CPU modes and
        settings.

        This computes some derived properties that are used in multilple
        places.

        :returns self:
        """
        self._collect_encoding_recipes()
        self._collect_predicates()
        self._collect_regclasses()
        return self

    def _collect_encoding_recipes(self):
        # type: () -> None
        """
        Collect and number all encoding recipes in use.
        """
        self.all_recipes = list()  # type: List[EncRecipe]
        rcps = set()  # type: Set[EncRecipe]
        for cpumode in self.cpumodes:
            for enc in cpumode.encodings:
                recipe = enc.recipe
                if recipe not in rcps:
                    recipe.number = len(rcps)
                    rcps.add(recipe)
                    self.all_recipes.append(recipe)

    def _collect_predicates(self):
        # type: () -> None
        """
        Collect and number all predicates in use.

        Sets `instp.number` for all used instruction predicates and places them
        in `self.all_instps` in numerical order.

        Ensures that all ISA predicates have an assigned bit number in
        `self.settings`.
        """
        self.all_instps = list()  # type: List[PredNode]
        instps = set()  # type: Set[PredNode]
        for cpumode in self.cpumodes:
            for enc in cpumode.encodings:
                instp = enc.instp
                if instp and instp not in instps:
                    # assign predicate number starting from 0.
                    instp.number = len(instps)
                    instps.add(instp)
                    self.all_instps.append(instp)

                # All referenced ISA predicates must have a number in
                # `self.settings`. This may cause some parent predicates to be
                # replicated here, which is OK.
                if enc.isap:
                    self.settings.number_predicate(enc.isap)

    def _collect_regclasses(self):
        # type: () -> None
        """
        Collect and number register classes.

        Every register class needs a unique index, and the classes need to be
        topologically ordered.
        """
        rc_index = 0
        for bank in self.regbanks:
            bank.finish_regclasses(rc_index)
            rc_index += len(bank.classes)


class CPUMode(object):
    """
    A CPU mode determines which instruction encodings are active.

    All instruction encodings are associated with exactly one `CPUMode`, and
    all CPU modes are associated with exactly one `TargetISA`.

    :param name: Short mnemonic name for the CPU mode.
    :param target: Associated `TargetISA`.
    """

    def __init__(self, name, isa):
        # type: (str, TargetISA) -> None
        self.name = name
        self.isa = isa
        self.encodings = []  # type: List[Encoding]
        isa.cpumodes.append(self)

    def __str__(self):
        # type: () -> str
        return self.name

    def enc(self, *args, **kwargs):
        # type: (*Any, **Any) -> None
        """
        Add a new encoding to this CPU mode.

        Arguments are the `Encoding constructor arguments, except for the first
        `CPUMode argument which is implied.
        """
        self.encodings.append(Encoding(self, *args, **kwargs))


class EncRecipe(object):
    """
    A recipe for encoding instructions with a given format.

    Many different instructions can be encoded by the same recipe, but they
    must all have the same instruction format.

    The `ins` and `outs` arguments are tuples specifying the register
    allocation constraints for the value operands and results respectively. The
    possible constraints for an operand are:

    - A `RegClass` specifying the set of allowed registers.
    - A `Register` specifying a fixed-register operand.
    - An integer indicating that this result is tied to a value operand, so
      they must use the same register.

    The `branch_range` argument must be provided for recipes that can encode
    branch instructions. It is an `(origin, bits)` tuple describing the exact
    range that can be encoded in a branch instruction.

    :param name: Short mnemonic name for this recipe.
    :param format: All encoded instructions must have this
            :py:class:`InstructionFormat`.
    :param size: Number of bytes in the binary encoded instruction.
    :param: ins Tuple of register constraints for value operands.
    :param: outs Tuple of register constraints for results.
    :param: branch_range `(origin, bits)` range for branches.
    :param: instp Instruction predicate.
    :param: isap ISA predicate.
    """

    def __init__(
            self,
            name,               # type: str
            format,             # type: InstructionFormat
            size,               # type: int
            ins,                # type: ConstraintSeq
            outs,               # type: ConstraintSeq
            branch_range=None,  # type: BranchRange
            instp=None,         # type: PredNode
            isap=None           # type: PredNode
            ):
        # type: (...) -> None
        self.name = name
        self.format = format
        assert size >= 0
        self.size = size
        self.branch_range = branch_range
        self.instp = instp
        self.isap = isap
        if instp:
            assert instp.predicate_context() == format
        self.number = None  # type: int

        self.ins = self._verify_constraints(ins)
        if not format.has_value_list:
            assert len(self.ins) == format.num_value_operands
        self.outs = self._verify_constraints(outs)

    def __str__(self):
        # type: () -> str
        return self.name

    def _verify_constraints(self, seq):
        # type: (ConstraintSeq) -> Sequence[OperandConstraint]
        if not isinstance(seq, tuple):
            seq = (seq,)
        for c in seq:
            if isinstance(c, int):
                # An integer constraint is bound to a value operand.
                # Check that it is in range.
                assert c >= 0
                if not self.format.has_value_list:
                    assert c < self.format.num_value_operands
            else:
                assert isinstance(c, RegClass) or isinstance(c, Register)
        return seq


class Encoding(object):
    """
    Encoding for a concrete instruction.

    An `Encoding` object ties an instruction opcode with concrete type
    variables together with and encoding recipe and encoding bits.

    The concrete instruction can be in three different forms:

    1. A naked opcode: `trap` for non-polymorphic instructions.
    2. With bound type variables: `iadd.i32` for polymorphic instructions.
    3. With operands providing constraints: `icmp.i32(intcc.eq, x, y)`.

    If the instruction is polymorphic, all type variables must be provided.

    :param cpumode: The CPU mode where the encoding is active.
    :param inst: The :py:class:`Instruction` or :py:class:`BoundInstruction`
                 being encoded.
    :param recipe: The :py:class:`EncRecipe` to use.
    :param encbits: Additional encoding bits to be interpreted by `recipe`.
    :param instp: Instruction predicate, or `None`.
    :param isap: ISA predicate, or `None`.
    """

    def __init__(self, cpumode, inst, recipe, encbits, instp=None, isap=None):
        # type: (CPUMode, InstSpec, EncRecipe, int, PredNode, PredNode) -> None # noqa
        assert isinstance(cpumode, CPUMode)
        assert isinstance(recipe, EncRecipe)

        # Check for possible instruction predicates in `inst`.
        if isinstance(inst, Apply):
            instp = And.combine(instp, inst.inst_predicate())
            self.inst = inst.inst
            self.typevars = inst.typevars
        else:
            self.inst, self.typevars = inst.fully_bound()

        self.cpumode = cpumode
        assert self.inst.format == recipe.format, (
                "Format {} must match recipe: {}".format(
                    self.inst.format, recipe.format))

        if self.inst.is_branch:
            assert recipe.branch_range, (
                    'Recipe {} for {} must have a branch_range'
                    .format(recipe, self.inst.name))

        self.recipe = recipe
        self.encbits = encbits
        # Combine recipe predicates with the manually specified ones.
        self.instp = And.combine(recipe.instp, instp)
        self.isap = And.combine(recipe.isap, isap)

    def __str__(self):
        # type: () -> str
        return '[{}#{:02x}]'.format(self.recipe, self.encbits)

    def ctrl_typevar(self):
        # type: () -> ValueType
        """
        Get the controlling type variable for this encoding or `None`.
        """
        if self.typevars:
            return self.typevars[0]
        else:
            return None
