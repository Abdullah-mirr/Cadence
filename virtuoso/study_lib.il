;; builds the gmid_study library: nmos_dut / pmos_dut (schematic + symbol)
;; and the two test benches nmos_tb / pmos_tb
;;
;; in the CIW:
;;   load("<path>/virtuoso/study_lib.il")
;;   studyLibSetup()
;; can be run again, cells get redrawn

;; settings (change only if needed)
studyLibName  = "gmid_study"
studyLibDir   = nil        ; nil -> <virtuoso start folder>/gmid_study
studyPdkLib   = nil        ; nil -> found automatically (lib with nch symbol)
studyNmosCell = "nch"
studyPmosCell = "pch"
studyW        = "1u"
studyL        = "60n"
studyGrid     = 0.0625
studyStub     = 0.25
studyOk       = 0
studyFailed   = 0

;; small helpers
procedure(studyStep(text okFlag)
  if(okFlag then
    studyOk = studyOk + 1
    printf("  OK      %s\n" text)
  else
    studyFailed = studyFailed + 1
    printf("  FAILED  %s\n" text)
  )
  okFlag
)

procedure(studySnap(v)
  round(v / studyGrid) * studyGrid
)

;; centre point of a bounding box ((x1 y1) (x2 y2))
procedure(studyCenter(box)
  let((x1 y1 x2 y2 xc yc)
    x1 = xCoord(car(box))
    y1 = yCoord(car(box))
    x2 = xCoord(cadr(box))
    y2 = yCoord(cadr(box))
    xc = 0.5 * x1 + 0.5 * x2
    yc = 0.5 * y1 + 0.5 * y2
    list(xc yc)
  )
)

;; find the first library that has <cellName>/symbol
procedure(studyFindPdk(cellName)
  let((found)
    foreach(lib ddGetLibList()
      when(!found && ddGetObj(lib~>name cellName "symbol")
        found = lib~>name
      )
    )
    found
  )
)

;; connection point of terminal <term> of instance <inst>,
;; in the coordinates of the cell that holds the instance
procedure(studyTermPoint(inst term)
  let((pin box)
    pin = car(term~>pins)
    box = pin && pin~>fig && pin~>fig~>bBox
    when(box
      dbTransformPoint(studyCenter(box) inst~>transform)
    )
  )
)

;; end point of a short wire that leaves the instance outwards
procedure(studyStubEnd(inst pt)
  let((c dx dy)
    c  = studyCenter(inst~>bBox)
    dx = xCoord(pt) - xCoord(c)
    dy = yCoord(pt) - yCoord(c)
    if(abs(dx) >= abs(dy) then
      if(dx >= 0 then
        studySnap(xCoord(pt) + studyStub):studySnap(yCoord(pt))
      else
        studySnap(xCoord(pt) - studyStub):studySnap(yCoord(pt))
      )
    else
      if(dy >= 0 then
        studySnap(xCoord(pt)):studySnap(yCoord(pt) + studyStub)
      else
        studySnap(xCoord(pt)):studySnap(yCoord(pt) - studyStub)
      )
    )
  )
)

;; draw a stub on every terminal of <inst> and label it with a net name.
;; netMap is a list of (terminalNameLowerCase netName) pairs.
procedure(studyConnect(cv inst netMap)
  let((pt endPt wires net okAll)
    okAll = t
    foreach(term inst~>master~>terminals
      net = cadr(assoc(lowerCase(term~>name) netMap))
      pt  = studyTermPoint(inst term)
      cond(
        (!net
          printf("          no net given for %s.%s\n" inst~>name term~>name)
          okAll = nil)
        (!pt
          printf("          no pin shape for %s.%s\n" inst~>name term~>name)
          okAll = nil)
        (t
          endPt = studyStubEnd(inst pt)
          wires = schCreateWire(cv "draw" "full" list(pt endPt) studyGrid studyGrid 0.0)
          if(wires then
            schCreateWireLabel(cv car(wires) endPt net "lowerLeft" "R0" "stick" studyGrid nil)
          else
            okAll = nil
          )
        )
      )
    )
    okAll
  )
)

;; set CDF parameters, e.g. list(list("w" "1u") list("l" "60n"))
procedure(studySetCdf(inst params)
  let((cdf param okAll)
    okAll = t
    cdf = car(errset(cdfGetInstCDF(inst) t))
    unless(cdf okAll = nil)
    when(cdf
      foreach(p params
        param = cdfFindParamByName(cdf car(p))
        unless(param && errset(param~>value = cadr(p) t)
          printf("          could not set %s on %s\n" car(p) inst~>name)
          okAll = nil
        )
      )
    )
    okAll
  )
)

;; 2. library
procedure(studyMakeLib()
  let((dir lib cdsLib inPort line found outPort)
    dir = or(studyLibDir strcat(getWorkingDir() "/" studyLibName))
    lib = ddGetObj(studyLibName)
    unless(lib
      lib = ddCreateLib(studyLibName dir)
    )
    studyStep(sprintf(nil "library %s at %s" studyLibName dir) lib)

    ;; make sure cds.lib in the start folder defines the library
    cdsLib = strcat(getWorkingDir() "/cds.lib")
    found = nil
    when(isFile(cdsLib)
      inPort = infile(cdsLib)
      when(inPort
        while(gets(line inPort)
          when(rexMatchp(strcat("DEFINE[ \t]+" studyLibName "[ \t]") line)
            found = t
          )
        )
        close(inPort)
      )
    )
    unless(found
      outPort = outfile(cdsLib "a")
      when(outPort
        fprintf(outPort "DEFINE %s %s\n" studyLibName dir)
        close(outPort)
        found = t
      )
    )
    studyStep(sprintf(nil "cds.lib has DEFINE %s" studyLibName) found)
    lib
  )
)

;; 3. technology attach
procedure(studyAttachTech(lib)
  studyStep(sprintf(nil "attach %s to technology of %s" studyLibName studyPdkLib)
            or(errset(techSetTechLibName(lib studyPdkLib) t)
               errset(techBindTechFile(lib studyPdkLib) t)))
)

;; 4 / 5. device cell: schematic with pins, then symbol
procedure(studyMakeDut(cellName pdkCell)
  let((cv master pinMaster inst pt endPt wires ok)
    ok = t
    cv        = dbOpenCellViewByType(studyLibName cellName "schematic" "schematic" "w")
    master    = dbOpenCellViewByType(studyPdkLib pdkCell "symbol")
    pinMaster = dbOpenCellViewByType("basic" "iopin" "symbol")
    if(!cv || !master || !pinMaster then
      studyStep(sprintf(nil "%s schematic (could not open views)" cellName) nil)
    else
      inst = dbCreateInst(cv master "M0" 0:0 "R0")
      studyStep(sprintf(nil "%s: placed %s/%s" cellName studyPdkLib pdkCell) inst)
      studyStep(sprintf(nil "%s: set w=%s l=%s" cellName studyW studyL)
                studySetCdf(inst list(list("w" studyW) list("l" studyL))))
      foreach(term inst~>master~>terminals
        pt = studyTermPoint(inst term)
        if(pt then
          endPt = studyStubEnd(inst pt)
          wires = schCreateWire(cv "draw" "full" list(pt endPt) studyGrid studyGrid 0.0)
          unless(wires ok = nil)
          unless(schCreatePin(cv pinMaster lowerCase(term~>name) "inputOutput" nil endPt "R0")
            ok = nil
          )
        else
          ok = nil
        )
      )
      studyStep(sprintf(nil "%s: pins d g s b" cellName) ok)
      schCheck(cv)
      studyStep(sprintf(nil "%s: check and save schematic" cellName) dbSave(cv))
      dbClose(cv)
      studyStep(sprintf(nil "%s: symbol view" cellName) studyMakeSymbol(cellName))
    )
  )
)

procedure(studyMakeSymbol(cellName)
  let((pins)
    or(
      car(errset(schViewToView(studyLibName cellName studyLibName cellName
                               "schematic" "symbol"
                               "schSchemToPinList" "schPinListToSymbol") t))
      car(errset(progn(
        pins = schSchemToPinList(studyLibName cellName "schematic")
        schPinListToSymbol(studyLibName cellName "symbol" pins)) t))
    )
  )
)

;; 6 / 7. test benches
;; parts: list of (instName libName cellName x y vdcValue netMap)
;; (all coordinates are positive on purpose: in SKILL  a -1  can be read as  a - 1)
procedure(studyMakeTb(cellName parts)
  let((cv master inst ok name)
    ok = t
    cv = dbOpenCellViewByType(studyLibName cellName "schematic" "schematic" "w")
    if(!cv then
      studyStep(sprintf(nil "%s schematic (could not open)" cellName) nil)
    else
      foreach(p parts
        name   = nth(0 p)
        master = dbOpenCellViewByType(nth(1 p) nth(2 p) "symbol")
        if(!master then
          printf("          cannot open %s/%s/symbol\n" nth(1 p) nth(2 p))
          ok = nil
        else
          if(nth(5 p) then
            inst = dbCreateParamInst(cv master name nth(3 p):nth(4 p) "R0" 1
                                     list(list("vdc" "string" nth(5 p))))
          else
            inst = dbCreateInst(cv master name nth(3 p):nth(4 p) "R0")
          )
          unless(inst && studyConnect(cv inst nth(6 p))
            ok = nil
          )
        )
      )
      studyStep(sprintf(nil "%s: instances and connections" cellName) ok)
      schCheck(cv)
      studyStep(sprintf(nil "%s: check and save" cellName) dbSave(cv))
      dbClose(cv)
    )
  )
)

;; 8. report
procedure(studyReport()
  let((lib file port)
    lib  = ddGetObj(studyLibName)
    file = strcat(getWorkingDir() "/gmid_study_report.txt")
    port = outfile(file)
    when(lib && port
      fprintf(port "Library : %s\n" lib~>name)
      fprintf(port "Path    : %s\n" lib~>readPath)
      fprintf(port "Tech    : %L\n" car(errset(techGetTechLibName(lib) t)))
      fprintf(port "PDK lib : %s\n\n" studyPdkLib)
      fprintf(port "Cell            Views\n")
      foreach(cell lib~>cells
        fprintf(port "%-15s %s\n" cell~>name
                buildString(mapcar(lambda((v) v~>name) cell~>views) " "))
      )
      close(port)
    )
    studyStep(sprintf(nil "report written to %s" file) lib && port)
  )
)

;; main
procedure(studyLibSetup()
  let((lib)
    studyOk = 0
    studyFailed = 0
    printf("\n==== study library set-up ====\n")

    unless(studyPdkLib
      studyPdkLib = studyFindPdk(studyNmosCell)
    )
    if(!studyStep(sprintf(nil "PDK library with %s: %L" studyNmosCell studyPdkLib) studyPdkLib) then
      printf("Set studyPdkLib = \"<pdk library name>\" in the CIW and run again.\n")
    else
      lib = studyMakeLib()
      when(lib
        studyAttachTech(lib)
        studyMakeDut("nmos_dut" studyNmosCell)
        studyMakeDut("pmos_dut" studyPmosCell)

        ;; NMOS bench: source/body to ground, gate = VGS, drain = VDS
        studyMakeTb("nmos_tb"
          list(
            list("X0"  studyLibName "nmos_dut" 5.0  4.0 nil
                 list(list("d" "d") list("g" "g") list("s" "gnd!") list("b" "gnd!")))
            list("VGS" "analogLib"  "vdc"      3.0  3.0 "VGS"
                 list(list("plus" "g") list("minus" "gnd!")))
            list("VDS" "analogLib"  "vdc"      7.5  5.0 "VDS"
                 list(list("plus" "d") list("minus" "gnd!")))
            list("G0"  "analogLib"  "gnd"      5.0  1.5 nil
                 list(list("gnd!" "gnd!")))
          ))

        ;; PMOS bench: source/body on VSUP, gate and drain referred to the source
        ;;   V(g) = VSUP - VSG ,  V(d) = VSUP - VSD
        studyMakeTb("pmos_tb"
          list(
            list("X0"   studyLibName "pmos_dut" 6.0  4.0 nil
                 list(list("d" "d") list("g" "g") list("s" "s") list("b" "s")))
            list("VSUP" "analogLib"  "vdc"      2.0  3.0 "VSUP"
                 list(list("plus" "s") list("minus" "gnd!")))
            list("VSG"  "analogLib"  "vdc"      4.0  5.5 "VSG"
                 list(list("plus" "s") list("minus" "g")))
            list("VSD"  "analogLib"  "vdc"      8.5  5.5 "VSD"
                 list(list("plus" "s") list("minus" "d")))
            list("G0"   "analogLib"  "gnd"      2.0  1.0 nil
                 list(list("gnd!" "gnd!")))
          ))
        studyReport()
      )
    )
    printf("==== done: %d OK, %d FAILED ====\n\n" studyOk studyFailed)
    studyFailed == 0
  )
)

printf("study_lib.il loaded. Type  studyLibSetup()  to build the library.\n")
